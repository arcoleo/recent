#!/usr/bin/env python
import argparse
import configparser
import hashlib
import os
import re
import sys
import socket
import sqlite3
import logging
from pprint import pprint

import psycopg2

SCHEMA_VERSION = 1

format = "%(asctime)s %(levelname)s [%(filename)s:%(lineno)s:%(funcName)s] %(message)s"
logging.basicConfig(format=format)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class Term:

    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class SQL:

    INSERT_ROW = """INSERT INTO commands (command_dt, command, pid, return_val, pwd, session)
        VALUES (datetime('now','localtime'), %s, %s, %s, %s, %s)"""
    INSERT_SESSION = """INSERT INTO sessions (created_dt, updated_dt, term, hostname, user, sequence, session)
        VALUES (datetime('now','localtime'), datetime('now','localtime'), %s, %s, %s, %s, %s)"""
    UPDATE_SESSION = """UPDATE sessions SET updated_dt = datetime('now','localtime'), sequence = %s
        WHERE session = %s"""
    TAIL_N_ROWS = """SELECT command_dt, command FROM commands ORDER BY command_dt DESC LIMIT %s"""

    DROP_COMMANDS_TABLE = """DROP TABLE IF EXISTS commands CASCADE"""
    CREATE_COMMANDS_TABLE = """CREATE TABLE IF NOT EXISTS commands (pk INTEGER PRIMARY KEY, command_dt TIMESTAMP, command TEXT, pid INT, return_val INT, pwd TEXT, session_fk INTEGER)"""
    DROP_SESSIONS_TABLE = """DROP TABLE IF EXISTS sessions CASCADE"""
    CREATE_SESSIONS_TABLE = """CREATE TABLE IF NOT EXISTS sessions (pk INTEGER PRIMARY KEY, session TEXT NOT NULL, created_dt TIMESTAMP, updated_dt TIMESTAMP, term TEXT, hostname TEXT, username TEXT, sequence INT)"""

    CREATE_DATE_INDEX = """CREATE INDEX IF NOT EXISTS command_dt_ind ON commands (command_dt)"""
    GET_SESSION_SEQUENCE = """SELECT sequence FROM sessions WHERE session = ?"""

    MIGRATE_0_1 = "ALTER TABLE commands ADD COLUMN session TEXT"


class SQLITE(SQL):
    CHECK_COMMANDS_TABLE = """SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table' AND name='commands'"""
    GET_SCHEMA_VERSION = """PRAGMA user_version"""
    UPDATE_SCHEMA_VERSION = """PRAGMA user_version = """


class PGSQL(SQL):
    CHECK_COMMANDS_TABLE = """SELECT COUNT(*) AS count FROM sqlite_master WHERE type='table' AND name='commands'"""


class Session:
    def __init__(self, sequence, command, pid, return_value, pwd, connection):
        self.sequence = sequence
        self.command = command
        self.pid = pid
        self.return_value = return_value
        self.pwd = pwd
        self.empty = False
        self.connection = connection
        # This combinaton of ENV vars *should* provide a unique session
        # TERM_SESSION_ID for OS X Terminal
        # XTERM for xterm
        # TMUX, TMUX_PANE for tmux
        # STY for GNU screen
        # SHLVL handles nested shells
        seed = "{}-{}-{}-{}-{}-{}-{}".format(
            os.getenv('TERM_SESSION_ID', ''), os.getenv('WINDOWID', ''),
            os.getenv('SHLVL', ''), os.getenv('TMUX', ''),
            os.getenv('TMUX_PANE', ''), os.getenv('STY', ''), pid)
        self.id = hashlib.md5(seed.encode('utf-8')).hexdigest()

    def update(self):
        self.cursor = self.connection.conn.cursor()
        self.term = os.getenv('TERM', '')
        self.hostname = socket.gethostname()
        self.user = os.getenv('USER', '')

    def insert_row(self):
        if not self.empty:
            self.connection.exec_sql(
                SQL.INSERT_ROW,
                [self.command, self.pid, self.return_value, self.pwd, self.id])
        self.connection.conn.close()


class PGSQLSession(Session):
    def __init__(self, sequence, command, pid, return_value, pwd, connection):
        super().__init__(self, sequence, command, pid, return_value,
                         connection)
        self.sql = PGSQL

    def update(self):
        super().update()
        self.connection.exec_sql(
            self.sql.INSERT_SESSION,
            [self.term, self.hostname, self.user, self.sequence, self.id])


class SQLITESession(Session):
    def __init__(self, sequence, command, pid, return_value, pwd, connection):
        super().__init__(self, sequence, command, pid, return_value,
                         connection)
        self.sql = SQLITE

    def update(self):
        super().update()
        self.connection.exec_sql(
            self.sql.INSERT_SESSION,
            [self.term, self.hostname, self.user, self.sequence, self.id])
        # try:
        #     self.cursor.execute(self.sql.INSERT_SESSION,
        #                         [term, hostname, user, self.sequence, self.id])
        #     self.empty = True
        # except sqlite3.IntegrityError:
        #     # Carriage returns need to be ignored
        #     if c.execute(self.sql.GET_SESSION_SEQUENCE,
        #                  [self.id]).fetchone()[0] == int(self.sequence):
        #         self.empty = True
        #     c.execute(self.sql.UPDATE_SESSION, [self.sequence, self.id])


def migrate(self, version, conn):
    if version > SCHEMA_VERSION:
        exit(
            Term.FAIL +
            'recent: your command history database does not match recent, please update'
            + Term.ENDC)

    c = conn.cursor()
    if version == 0:
        if c.execute(self.sql.CHECK_COMMANDS_TABLE).fetchone()[0] != 0:
            print(Term.WARNING + 'recent: migrating schema to version {}'.
                  format(SCHEMA_VERSION) + Term.ENDC)
            c.execute(self.sql.MIGRATE_0_1)
        else:
            print(Term.WARNING + 'recent: building schema' + Term.ENDC)
        c.execute(self.sql.CREATE_COMMANDS_TABLE)
        c.execute(self.sql.CREATE_SESSIONS_TABLE)
        c.execute(self.sql.CREATE_DATE_INDEX)

    c.execute(self.sql.UPDATE_SCHEMA_VERSION + str(SCHEMA_VERSION))
    conn.commit()


def parse_history(history):
    match = re.search(r'^\s+(\d+)\s+(.*)$', history, re.MULTILINE
                      and re.DOTALL)
    if match:
        return (match.group(1), match.group(2))

    return (None, None)


def parse_date(date_format):
    if re.match(r'^\d{4}$', date_format):
        return 'strftime(\'%Y\', command_dt) = ?'
    if re.match(r'^\d{4}-\d{2}$', date_format):
        return 'strftime(\'%Y-%m\', command_dt) = ?'
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_format):
        return 'date(command_dt) = ?'
    return 'command_dt = ?'


class DBConnection:
    def __init__(self, configs):
        self.configs = configs

    def query_builder(self):
        logger.debug('begin')
        query = SQL.TAIL_N_ROWS
        logger.debug('query: [%s]', query)
        filters = []
        parameters = []
        if 'pattern' in self.configs.keys():
            logger.debug('pattern in keys()')
            filters.append('command like ?')
            parameters.append('%' + self.configs.get('pattern') + '%')
        if 'working_dir' in self.configs.keys():
            logger.debug('working_dir in keys()')
            filters.append('pwd = ?')
            parameters.append(
                os.path.abspath(
                    os.path.expanduser(self.configs.get('working_dir'))))
        if 'date_format' in self.configs.keys():
            logger.debug('date_format in keys()')
            filters.append(parse_date(self.configs.get('date_format')))
            parameters.append(self.configs.get('date_format'))

        try:
            max_results = int(self.configs.get('max_results'))
            parameters.append(max_results)
        except:
            exit(Term.FAIL + '--max-results must be a integer' + Term.ENDC)
        where = 'WHERE ' + ' AND '.join(filters) if len(filters) > 0 else ''
        return (query.replace('where', where), parameters)


class SQLITEConnection(DBConnection):
    def __init__(self, configs):
        super().__init__(configs)
        self.conn = sqlite3.connect(configs['db_name'])


class PGSQLConnection(DBConnection):
    SQL = PGSQL

    def __init__(self, configs):
        super().__init__(configs)
        self.conn_params = None
        self.conn = None
        self.current_version = 0
        self.connect()
        self.build_schema()
        self.migrate()

        query, parameters = self.query_builder()
        logger.info(query)
        logger.info(parameters)

        results = self.exec_sql(query, parameters)
        if not results:
            return
        for row in results:
            # for row in c.execute(query, parameters):
            if row[0] and row[1]:
                print(Term.WARNING + row[0] + Term.ENDC + ' ' + row[1])

    def exec_sql(self, query, parameters=None):
        logger.debug('begin')
        logger.debug(query)
        logger.debug(parameters)
        cursor = self.conn.cursor()
        if parameters is None:
            parameters = ()

        try:
            results = cursor.execute(query, parameters)
        except psycopg2.ProgrammingError as ex:
            logger.exception(ex)
            raise
        except psycopg2.InternalError as ex:
            logger.exception(ex)
        logger.debug('end')
        self.conn.commit()
        return results

    def connect(self):
        conn_params = {
            'dbname': self.configs['db_name'],
            'user': self.configs['db_user'],
            'password': self.configs['db_password']
        }
        if 'db_host' in self.configs.keys():
            conn_params['host'] = self.configs['db_host']
        if 'db_port' in self.configs.keys():
            conn_params['port'] = self.configs['db_port']
        self.conn = psycopg2.connect(**conn_params)

    def build_schema(self):
        # cursor = self.conn.cursor()
        pass

    def migrate(self):
        # if version > SCHEMA_VERSION:
        #     exit(
        #         Term.FAIL +
        #         'recent: your command history database does not match recent, please update'
        #         + Term.ENDC)

        # cursor = self.conn.cursor()
        if self.current_version == 0:
            # if c.execute(SQL.CHECK_COMMANDS_TABLE).fetchone()[0] != 0:
            #     print(Term.WARNING + 'recent: migrating schema to version {}'.
            #           format(SCHEMA_VERSION) + Term.ENDC)
            #     c.execute(self.sql.MIGRATE_0_1)
            # else:
            #     print(Term.WARNING + 'recent: building schema' + Term.ENDC)
            self.exec_sql(SQL.DROP_COMMANDS_TABLE)
            self.exec_sql(SQL.CREATE_COMMANDS_TABLE)

            self.exec_sql(SQL.DROP_SESSIONS_TABLE)
            self.exec_sql(SQL.CREATE_SESSIONS_TABLE)

            self.exec_sql(SQL.CREATE_DATE_INDEX)

        # c.execute(SQL.UPDATE_SCHEMA_VERSION + str(SCHEMA_VERSION))
        # self.conn.commit()


def create_connection(configs):
    # recent_db = os.getenv('RECENT_DB', os.environ['HOME'] + '/.recent.db')
    if configs['db'] == 'pgsql':
        connection = PGSQLConnection(configs)
    else:
        print('DB type not yet configured')

    # build_schema(conn)
    return connection


def build_schema(conn):
    try:
        c = conn.cursor()
        current = c.execute(SQL.GET_SCHEMA_VERSION).fetchone()[0]
        if current != SCHEMA_VERSION:
            migrate(current, conn)
    except (sqlite3.OperationalError, TypeError) as e:
        migrate(0, conn)


def log():
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--return_value', help='set to $?', default=0)
    parser.add_argument(
        '-c',
        '--command',
        help='set to $(HISTTIMEFORMAT= history 1)',
        default='')
    parser.add_argument('-p', '--pid', help='set to $$', default=0)
    args = parser.parse_args()

    logger.debug('Hello World')

    sequence, command = parse_history(args.command)
    pid, return_value = args.pid, args.return_value
    pwd = os.getenv('PWD', '')

    if sequence is None or command is None:
        print(
            Term.WARNING +
            'recent: cannot parse command output, please check your bash trigger looks like this:'
            + Term.ENDC)
        print(
            """export PROMPT_COMMAND='log-recent -r $? -c "$(HISTTIMEFORMAT= history 1)" -p $$'"""
        )
        exit(1)
    configs = load_configs(args)
    connection = create_connection(configs)

    if configs['db'] == 'pgsql':
        session = PGSQLSession(sequence, command, pid, return_value, pwd,
                               connection)
    else:
        print('DB type not yet configured')

    session.update()

    session.insert_row()

    # if not session.empty:
    #     c = connection.conn.cursor()
    #     c.execute(SQL.INSERT_ROW,
    #               [command, pid, return_value, pwd, session.id])

    # connection.conn.commit()
    # conn.close()


# def query_builder(args):
#     query = SQL.TAIL_N_ROWS
#     filters = []
#     parameters = []
#     if (args.pattern != ''):
#         filters.append('command like ?')
#         parameters.append('%' + args.pattern + '%')
#     if (args.w != ''):
#         filters.append('pwd = ?')
#         parameters.append(os.path.abspath(os.path.expanduser(args.w)))
#     if (args.d != ''):
#         filters.append(parse_date(args.d))
#         parameters.append(args.d)
#     try:
#         n = int(args.n)
#         parameters.append(n)
#     except:
#         exit(Term.FAIL + '-n must be a integer' + Term.ENDC)
#     where = 'where ' + ' and '.join(filters) if len(filters) > 0 else ''
#     return (query.replace('where', where), parameters)


def load_configs(args):
    logger.debug('begin')
    config = configparser.ConfigParser()
    config.read(os.path.expanduser(args.rc_file))

    config_dict = dict(config['general'])
    db_dict = dict(config[config_dict['db']])
    del_list = []
    # delete empty values
    for k, v in db_dict.items():
        if v is None or v == '':
            del_list.append(k)
    for item in del_list:
        del db_dict[item]
    config_dict.update(db_dict)

    # command line options override config file
    for item, value in vars(args).items():
        if value is not None:
            config_dict[item] = value
    # pprint(config_dict)

    if config_dict.get('max_results') is None:
        config_dict['max_results'] = 20

    logger.debug('end')
    return config_dict


def main():
    logger.debug('HELLO')
    logger.error('SDFSDF')
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'pattern', nargs='?', help='optional pattern to search')
    parser.add_argument(
        '-m',
        '--max-results',
        type=int,
        default=20,
        help='max results to return',
    )
    parser.add_argument(
        '-w', '--working-dir', metavar=('/folder'), help='working directory')
    parser.add_argument(
        '-d',
        '--date-format',
        metavar=('2016-10-01'),
        help='date in YYYY-MM-DD, YYYY-MM, or YYYY format')
    parser.add_argument(
        '-n', '--db-name', help='Full db name, including path if sqlite')
    parser.add_argument('-c', '--rc-file', default='~/dsa_recent.cfg')
    args = parser.parse_args()
    configs = load_configs(args)
    _ = create_connection(configs)

    # c = conn.cursor()
    # sys.exit()
    # query, parameters = query_builder(args)
    # for row in c.execute(query, parameters):
    #     if row[0] and row[1]:
    #         print(Term.WARNING + row[0] + Term.ENDC + ' ' + row[1])
    # conn.close()


if __name__ == "__main__":
    main()

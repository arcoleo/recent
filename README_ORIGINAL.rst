== Recent

Recent is a more structured way to log your bash history.

The standard `~/.bash_history` file is inadequate in many ways, its
worst fault is to by default log only 500 history entries, with no timestamp.

You can alter your bash `HISTFILESIZE` and `HISTTIMEFORMAT` variables but it is still a unstructured format with limited querying ability.

Recent does the following:

. Logs current localtime, command text, current pid, command return value, working directory to an sqlite database in `~/.recent.db`.

. Logs history immediately, rather than at the close of the session.

. Provides a command called recent for searching logs.

== Installation instructions

You need will need sqlite installed.

Install the recent pip package:

[source,bash]
----
pip install recent
----

Add the following to your .bashrc or .bash_profile:

[source,bash]
----
export PROMPT_COMMAND='log-recent -r $? -c "$(HISTTIMEFORMAT= history 1)" -p $$'
----

And start a new shell.

== Usage

Look at your current history using recent:

[source,bash]
----
recent
----

Search for a pattern as follows:

[source,bash]
----
recent git
----

For more information see the help:

[source,bash]
----
recent -h
----

Not currently recent doesn't integrate with bash commands such as
Ctrl-R, but this is in the pipeline.

You can directly query your history using the following:

[source,bash]
----
sqlite3 ~/.recent.db "select * from commands limit 10"
----


=== Dev installation instructions

[source,bash]
----
git clone https://github.com/trengrj/recent && cd recent

pip install -e .
----

== Security

Please note, recent does not take into account enforcing logging
for security purposes. For this functionality on linux, have a
look at auditd http://people.redhat.com/sgrubb/audit/.

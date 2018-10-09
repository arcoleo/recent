#!/usr/bin/env python

from setuptools import setup  #, find_packages
import codecs
from os import path
# import sys
# import fastentrypoints

here = path.abspath(path.dirname(__file__))

with codecs.open(path.join(here, 'README.adoc'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='dsa_recent',
    version='0.1.3',
    description='log bash history to postgres',
    long_description=long_description,

    # The project's main homepage.
    url='https://github.com/arcoleo/recent',

    # Author details
    author='David Arcoleo',
    author_email='david@arcoleo.org',
    license='MIT',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Environment :: Console',
        'Topic :: System :: Logging',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    keywords='logging bash history database',
    py_modules=["recent"],
    entry_points={
        'console_scripts': [
            'log-recent=recent:log',
            'recent=recent:main',
        ],
    },
)

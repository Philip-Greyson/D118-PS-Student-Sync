"""Helper script to the main studentsync.py script that calls only a specific building so it can be scheduled as a task or for testing."""

from studentsync import *  # include the functions from the main studentsync.py file

sync_students('999999')

"""Helper script to the main studentsync.py script that calls all the buildings so it can be scheduled as a task or for testing.

In our district, it takes about an hour to process all 140000 students
"""

from studentsync import *  # include the functions from the main studentsync.py file

sync_students('full')

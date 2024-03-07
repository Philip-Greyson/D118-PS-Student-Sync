"""Helper script to the main studentsync.py script that calls only state reporting buildings so it can be scheduled as a task or for testing.

In our district, it takes about 20 minutes to process all ~8000 students
"""

from studentsync import *  # include the functions from the main studentsync.py file

sync_students('limited')

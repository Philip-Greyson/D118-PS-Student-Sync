# Needs the google-api-python-client, google-auth-httplib2 and the google-auth-oauthlib
# pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

from __future__ import print_function

import json
from re import A
from typing import get_type_hints

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# importing module
import oracledb # needed for connection to PowerSchool server (ordcle database)
import sys # needed for  non-scrolling display
import os # needed for environement variable reading
from datetime import *

# setup db connection
un = 'PSNavigator' #PSNavigator is read only, PS is read/write
pw = os.environ.get('POWERSCHOOL_DB_PASSWORD') #the password for the database account
cs = os.environ.get('POWERSCHOOL_PROD_DB') #the IP address, port, and database name to connect to
print("Username: " + str(un) + " |Password: " + str(pw) + " |Server: " + str(cs)) #debug so we can see where oracle is trying to connect to/with

# the password to use for new staff accounts
newPass = os.environ.get('NEW_USER_PASSWORD')
 # the string location of where suspended accounts should end up, change if this is different
suspended_OU = '/Suspended Accounts'
# string location of where where the graduated students should go
graduated_OU = '/Suspended Accounts/Graduated Students'
# Define a list of sub-OUs in GAdmin where users should not be moved out of. Used for special permissions, apps, licenses, etc
frozenOrgs = ['/Restricted', '/Adobe Licensed Students']
# List of names that some of the dummy/old accounts use so we can ignore them
# badnames = ['USE', 'Training1','Trianing2','Trianing3','Trianing4','Planning','Admin','NURSE','USER', 'USE ', 'TEST', 'TESTTT', 'DO NOT', 'DO', 'NOT', 'TBD', 'LUNCH']
badnames = ['Use', 'Training1','Trianing2','Trianing3','Trianing4','Planning','Admin','Nurse','User', 'Use ', 'Test', 'Testtt', 'Test22', 'Teststudent', 'Tester', 'Karentest']
# dictionary to hold the grade_level to sub-OU name strings
gradeOUs = {-2 : '/PreKindergarten', -1 : '/PreKindergarten', 0 : '/Kindergarten', 1 : '/1st', 2 : '/2nd', 3 : '/3rd', 4 : '/4th', 5 : '/5th', 6 : '/6th', 7 : '/7th', 8 : '/8th', 9 : '/9th', 10 : '/10th', 11 : '/11th', 12 : '/12th', 13 : '', 15: '', 99: ''}

# Google API Scopes that will be used. If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/admin.directory.user', 'https://www.googleapis.com/auth/admin.directory.group', 'https://www.googleapis.com/auth/admin.directory.group.member', 'https://www.googleapis.com/auth/admin.directory.orgunit', 'https://www.googleapis.com/auth/admin.directory.userschema']

def syncStudents(schoolMode):

    # Get credentials from json file, ask for permissions on scope or use existing token.json approval, then build the "service" connection to Google API
    creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('admin', 'directory_v1', credentials=creds)

    # define a custom exception class just for use with logging
    class badNameException(Exception):
        pass

    with oracledb.connect(user=un, password=pw, dsn=cs) as con: # create the connecton to the database
        with con.cursor() as cur:  # start an entry cursor
            with open('StudentLog.txt', 'w') as log:
                startDate = datetime.now()
                startTime = startDate.strftime('%H:%M:%S')
                print(f'Execution started at {startTime}')
                print(f'Execution started at {startTime}', file=log)

                # Start by getting a list of schools from the schools table view to get the school names, numbers, etc for use. If the mode is "full" we want all schools, if not we only want the main schools not excluded from state reporting
                if schoolMode == 'full':
                    cur.execute('SELECT name, school_number, abbreviation FROM schools ORDER BY school_number')
                elif schoolMode == 'limited':
                    cur.execute('SELECT name, school_number, abbreviation FROM schools WHERE State_ExcludeFromReporting = 0 ORDER BY school_number')
                else:
                    cur.execute('SELECT name, school_number, abbreviation FROM schools WHERE school_number = ' + schoolMode + ' ORDER BY school_number')
                
                schools = cur.fetchall() # store all the query results in the schools list
                for school in schools:
                    # store results in variables mostly just for readability
                    schoolName = school[0].title() # convert to title case since some are all caps
                    schoolNum = school[1]
                    schoolAbbrev = school[2]
                    # construct the string for the organization unit in Google Admin from the building name + students
                    orgUnit = '/D118 Students/' + schoolAbbrev + ' Students'
                    if schoolName == 'Graduated Students': # check and see if our building is the graduated students building since they have a different OU then the rest
                        orgUnit = graduated_OU
                    print(f'Starting Building: {schoolName} | {schoolNum} | {orgUnit}') # debug
                    print(f'Starting Building: {schoolName} | {schoolNum} | {orgUnit}',file=log) # debug
                    print('--------------------------------------------------------------------') # debug
                    print('--------------------------------------------------------------------',file=log) # debug

                    # query for all students in the curent school
                    cur.execute('SELECT student_number, first_name, last_name, classof, enroll_status, schoolid, grade_level FROM students WHERE schoolid = ' + str(schoolNum) + ' ORDER BY student_number DESC')
                    students = cur.fetchall()
                    for student in students:
                        try:
                            bodyDict = {} # define empty dict that will hold the update parameters
                            # print(student)
                            # print(student, file=log)
                            stuNum = int(student[0])
                            firstName = str(student[1]).title()
                            lastName = str(student[2]).title()
                            if firstName in badnames or lastName in badnames: # check their first and last names against the list of test/dummy accounts
                                raise badNameException('Found name that matches list of bad names') # raise an exception for them if they have a bad name, which skips the rest of processing
                            email = str(stuNum) + '@d118.org'
                            # print(email) # debug
                            # print(email, file=log) # debug
                            gradYear = int(student[3])
                            enroll = int(student[4])
                            school = int(student[5])
                            grade = int(student[6])

                            currentYear = int(startDate.strftime("%Y")) # get the current year as a integer from the start time
                            currentMonth = startDate.strftime("%B") # get the current month name as a string

                            suspended = False if enroll == 0 or enroll == -1 else True # create a flag for whether they should be suspended or not, will be based on their enroll status
                            # override graduated students being suspended for the months of july and august so they can still access their emails until september 1st
                            if gradYear == currentYear: # check current year against grad year
                                if currentMonth == "July" or currentMonth == "August": # check if it is currently July or August
                                    if schoolName == 'Graduated Students' and enroll == 3: # make sure the student is in the graduated students building and
                                        suspended = False
                                        print(f'WARNING: {email} is a {currentYear} graduate, they will remain active until September 1st')
                                        print(f'WARNING: {email} is a {currentYear} graduate, they will remain active until September 1st', file=log)
                

                            # set the OU path based on their school, grades, enroll status, etc
                            properOU = orgUnit + gradeOUs.get(grade) # for enabled accounts at normal buildings, they get the overall building OU + the grade level sub-OU
                            # have a section to set OU for pre registered and graduated students separately as it does not include any grade sub-ous
                            if school == 999999 or enroll == 3 or school == 901 or enroll == -1:
                                properOU = orgUnit
                            # if they are just suspended (but not graduated), they get the normal suspended OU
                            if suspended and (school != 999999 and enroll != 3): 
                                properOU = suspended_OU

                            
                            print(f'User {email}, Name: {firstName} {lastName}, school: {school}, grade: {grade}, graduation year: {gradYear}, enroll: {enroll}, suspended: {suspended}, OU path: {properOU}')
                            print(f'User {email}, Name: {firstName} {lastName}, school: {school}, grade: {grade}, graduation year: {gradYear}, enroll: {enroll}, suspended: {suspended}, OU path: {properOU}', file=log)

                            # next do a query in Google Admin for the students account based on their email
                            queryString = 'email=' + email # construct the query string which looks for the email
                            userToUpdate = service.users().list(customer='my_customer', domain='d118.org', maxResults=2, orderBy='email', projection='full', query=queryString).execute() # return a list of at most 2 users 

                            # process all the active students
                            if not suspended:
                                # print('enabled')
                                # print('enabled', file=log)
                                if userToUpdate.get('users'): # if we found a user in Google that matches the user email, they already exist and we just want to update any info
                                    frozen = False # define a flag for whether they are in a frozen OU, set to false initially

                                    # get info from their account
                                    currentlySuspended = userToUpdate.get('users')[0].get('suspended')
                                    currentOU = userToUpdate.get('users')[0].get('orgUnitPath')
                                    print(f'INFO: Student {email} already has an existing Google account, updating any info')
                                    # print(f'INFO: Student {email} already has an existing Google account, updating any info', file=log)

                                    # check to see if the user is enabled in Google, if not add that to the update body
                                    if currentlySuspended == True:
                                        bodyDict.update({'suspended': False})

                                    # Check to see if they are in the correct OU (which is based on home building assignment)
                                    if currentOU != properOU:
                                        for org in frozenOrgs: # go through our list of "frozen" OU paths which contain a few users with custom settings, licenses, etc
                                            if org in currentOU: # check and see if the frozen OU path is part of the OU they are currently in, if so set the frozen flag to True
                                                frozen = True
                                        if frozen: # if they are in a frozen OU we do not add the change, but just print out an info line for logging
                                            print(f'INFO: User {email} is in the frozen OU {currentOU} and will not be moved to {properOU}')
                                            print(f'INFO: User {email} is in the frozen OU {currentOU} and will not be moved to {properOU}', file=log)
                                        else: # if theyre not in a frozen OU they will have the orgunit change added to the body of the update
                                            print(f'ACTION: User {email} not in a frozen OU, will to be moved from {currentOU} to {properOU}')
                                            print(f'ACTION: User {email} not in a frozen OU, will to be moved from {currentOU} to {properOU}', file=log)
                                            bodyDict.update({'orgUnitPath' : properOU}) # add OU to body of the update
                                    
                                    # Check to see if the student's name has changed significantly, if so update the name in Google
                                    currentFirstName = userToUpdate.get('users')[0].get('name').get('givenName')
                                    currentLastName = userToUpdate.get('users')[0].get('name').get('familyName')
                                    if currentFirstName.upper() != firstName.upper():
                                        print(f'ACTION: User {email} has changed first name from {currentFirstName} to {firstName}, updating')
                                        print(f'ACTION: User {email} has changed first name from {currentFirstName} to {firstName}, updating', file=log)
                                        bodyDict.update({'name' : {'givenName' : firstName}})
                                        if currentLastName.upper() != lastName.upper():
                                            print(f'ACTION: User {email} has changed last name from {currentLastName} to {lastName}, updating')
                                            print(f'ACTION: User {email} has changed last name from {currentLastName} to {lastName}, updating', file=log)
                                            bodyDict.update({'name' : {'givenName': firstName, 'familyName' : lastName}})
                                    elif currentLastName.upper() != lastName.upper():
                                        print(f'ACTION: User {email} has changed last name from {currentLastName} to {lastName}, updating')
                                        print(f'ACTION: User {email} has changed last name from {currentLastName} to {lastName}, updating', file=log)
                                        bodyDict.update({'name' : {'familyName' : lastName}})

                                    # get custom attributes info from their google profile
                                    try: # put the retrieval of the custom data in a try/except block because some accounts might not have the data, which will then need to be added
                                        currentSchool = int(userToUpdate.get('users')[0].get('customSchemas').get('Synchronization_Data').get('Homeschool_ID')) # take the first user's custom schema homeschool id and store it
                                        currentGrad = int(userToUpdate.get('users')[0].get('customSchemas').get('Synchronization_Data').get('Graduation_Year')) # take the first user's custom schema homeschool id and store it
                                        if (currentSchool != school or currentGrad != gradYear):
                                            print(f'ACTION: Updating {email}. School from {currentSchool} to {school}, Graduation Year from {currentGrad} to {gradYear}')
                                            print(f'ACTION: Updating {email}. School from {currentSchool} to {school}, Graduation Year from {currentGrad} to {gradYear}', file=log)
                                            bodyDict.update({'customSchemas' : {'Synchronization_Data' : {'Homeschool_ID' : school, 'Graduation_Year' : gradYear}}})
                                    except Exception as er:
                                        print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})')
                                        print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})', file=log)
                                        print(f'ACTION: Updating {email}. School to {school}, Graduation Year to {gradYear}')
                                        print(f'ACTION: Updating {email}. School to {school}, Graduation Year to {gradYear}', file=log)
                                        bodyDict.update({'customSchemas' : {'Synchronization_Data' : {'Homeschool_ID' : school, 'Graduation_Year' : gradYear}}})
                                    
                                    # Finally, do the actual update of the user profile, using the bodyDict we have constructed in the above sections
                                    if bodyDict: # if there is anything in the body dict we want to update. if its empty we skip the update
                                        try:
                                            print(bodyDict) # debug
                                            print(bodyDict, file=log) # debug
                                            outcome = service.users().update(userKey = email, body=bodyDict).execute() # does the actual updating of the user profile
                                        except Exception as er:
                                            print(f'ERROR: cannot update {email} : {er}')
                                            print(f'ERROR: cannot update {email} : {er}', file=log)
                                # if there is no google result for our email query, we should try to create a new email account
                                else:
                                    print(f'ACTION: User {email} does not exist, will be created')
                                    print(f'ACTION: User {email} does not exist, will be created', file=log)
                                    try:
                                        # define the new user email, name, and all the basic fields
                                        newUser = {'primaryEmail' : email, 'name' : {'givenName' : firstName, 'familyName' : lastName}, 'password' : newPass, 'changePasswordAtNextLogin' : True,
                                                'orgUnitPath' : properOU,
                                                'customSchemas' : {'Synchronization_Data' : {'Homeschool_ID' : school, 'Graduation_Year' : gradYear}}}
                                        outcome = service.users().insert(body=newUser).execute() # does the actual account creation
                                    except Exception as er:
                                        print(f'ERROR on user account creation for {email}: {er}')
                                        print(f'ERROR on user account creation for {email}: {er}', file=log)

                            # process all the inactive students
                            else:
                                print(f'User {email} is inactive, should be suspended')
                                # print(f'User {email} is inactive, should be suspended', file=log)
                                if userToUpdate.get('users'): # if we found a user in Google that matches the user email, they already exist and we just want to update any info
                                    # get info from their account
                                    currentlySuspended = userToUpdate.get('users')[0].get('suspended')
                                    currentOU = userToUpdate.get('users')[0].get('orgUnitPath')
                                    if not currentlySuspended:
                                        print(f'ACTION: Suspending {email}')
                                        print(f'ACTION: Suspending {email}', file=log)
                                        bodyDict.update({'suspended' : True}) # add the suspended: True to the body of the update patch
                                    if currentOU != properOU:
                                        print(f'ACTION: Moving {email} to suspended OU {properOU}')
                                        print(f'ACTION: Moving {email} to suspended OU {properOU}', file=log)
                                        bodyDict.update({'orgUnitPath' : properOU}) # add the suspended OU to the org unit path for the update patch
                                    
                                    # finally do the update (suspend and move) if we have anything in the bodyDict
                                    if bodyDict:
                                        print(bodyDict)
                                        print(bodyDict, file=log)
                                        outcome = service.users().update(userKey = email, body=bodyDict).execute() # does the actual updating of the user profile

                                        # Remove the newly suspended user from any groups they were a member of
                                        userGroups = service.groups().list(userKey=email).execute().get('groups')
                                        if userGroups:
                                            for group in userGroups:
                                                name = group.get('name')
                                                groupEmail = group.get('email')
                                                print(f'{email} was a member of: {name} - {groupEmail}, they will be removed from the group')
                                                print(f'{email} was a member of: {name} - {groupEmail}, they will be removed from the group',file=log)
                                                service.members().delete(groupKey=groupEmail, memberKey=email).execute()
                                        else:
                                            print(f'Newly suspended account {email} was not in any groups, no removal needed')
                                            print(f'Newly suspended account {email} was not in any groups, no removal needed', file=log)
                                    else:
                                        print(f'\t{email} is already suspended in the correct suspended accounts OU, no update needed')
                                        # print(f'\t{email} is already suspended in the correct suspended accounts OU, no update needed', file=log)
                                else: # if we did not find any google accounts matching the email, just give a warning
                                    print(f'WARNING: Found inactive student {email} without Google account that matches.')
                                    print(f'WARNING: Found inactive student {email} without Google account that matches.', file=log)

                        except badNameException as er:
                            print(f'INFO: found user matching name in bad names list {email} - {firstName} {lastName}')
                            print(f'INFO: found user matching name in bad names list {email} - {firstName} {lastName}', file=log)
                        except Exception as er:
                            print(f'ERROR on {student[1]}: {er}')
                            print(f'ERROR on {student[1]}: {er}', file=log)
                endTime = datetime.now()
                endTime = endTime.strftime('%H:%M:%S')
                print(f'Execution ended at {endTime}')
                print(f'Execution ended at {endTime}', file=log)
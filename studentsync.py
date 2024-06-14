"""Script to sync Google profile information from PowerSchool.

https://github.com/Philip-Greyson/D118-PS-Student-Sync

Needs the google-api-python-client, google-auth-httplib2 and the google-auth-oauthlib
# pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
"""

import os  # needed for environement variable reading
from datetime import *
from re import A
from typing import get_type_hints

# importing module
import oracledb  # needed for connection to PowerSchool server (ordcle database)
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# setup db connection
DB_UN = os.environ.get('POWERSCHOOL_READ_USER')  # username for read-only database user
DB_PW = os.environ.get('POWERSCHOOL_DB_PASSWORD')  # the password for the database account
DB_CS = os.environ.get('POWERSCHOOL_PROD_DB')  # the IP address, port, and database name to connect to
print(f"Database Username: {DB_UN} |Password: {DB_PW} |Server: {DB_CS}")  # debug so we can see where oracle is trying to connect to/with


NEW_PASSWORD = os.environ.get('NEW_USER_PASSWORD')  # the password to use for new student accounts. Will be changed by entry of password into PS filed via password script sync later
OU_PREFIX = '/D118 Students/'  # the base part of the OU for the overall umbrella student OU
SUSPENDED_OU = '/Suspended Accounts'  # the string location of where suspended accounts should end up
GRADUATED_OU = '/Suspended Accounts/Graduated Students'  # string location of where where the graduated students should go
FROZEN_OUS = ['/Restricted', '/Adobe Licensed Students']  # Define a list of sub-OUs in GAdmin where users should not be moved out of. Used for special permissions, apps, licenses, etc
GRADUATED_SCHOOL_NAME = 'Graduated Students'  # full name of the building where graduated students are moved to

BAD_NAMES = ['use', 'training1','trianing2','trianing3','trianing4','planning','admin','nurse','user','use ','test','testtt','test22','teststudent','tester','karentest','returning student','whs','wgs','rcs','ccs','mms','wms']  # List of names that some of the dummy/old accounts use so we can ignore them
GRADE_OUS = {-2 : '/PreKindergarten', -1 : '/PreKindergarten', 0 : '/Kindergarten', 1 : '/1st', 2 : '/2nd', 3 : '/3rd', 4 : '/4th', 5 : '/5th', 6 : '/6th', 7 : '/7th', 8 : '/8th', 9 : '/9th', 10 : '/10th', 11 : '/11th', 12 : '/12th', 13 : '', 15: '', 99: ''}  # dictionary to hold the grade_level to sub-OU name strings

EMAIL_SUFFIX = '@d118.org'  # email domain
GRADUATED_ACTIVE_SUMMER = True  # true or false whether graduated students should be left active for july/august

GOOGLE_DOMAIN = 'd118.org'  # domain for google admin user searches
CUSTOM_ATTRIBUTE_CATEGORY = 'Synchronization_Data'  # the category name that the custom attributes will be in
CUSTOM_ATTRIBUTE_SCHOOL = 'Homeschool_ID'  # the field name for the homeschool id custom attribute
CUSTOM_ATTRIBUTE_GRADYEAR = 'Graduation_Year'  # the field name for the grad year custom attribute

# Google API Scopes that will be used. If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/admin.directory.user', 'https://www.googleapis.com/auth/admin.directory.group', 'https://www.googleapis.com/auth/admin.directory.group.member', 'https://www.googleapis.com/auth/admin.directory.orgunit', 'https://www.googleapis.com/auth/admin.directory.userschema']

def sync_students(school_mode: any) -> None:
    """Main function to sync students, needs to be called with 'full', 'limited', or a specific school number."""
    with open('StudentLog.txt', 'w') as log:
        startDate = datetime.now()
        startTime = startDate.strftime('%H:%M:%S')
        print(f'Execution started at {startTime}')
        print(f'Execution started at {startTime}', file=log)

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
        class BadNameExceptionError(Exception):
            pass

        with oracledb.connect(user=DB_UN, password=DB_PW, dsn=DB_CS) as con:  # create the connecton to the database
            with con.cursor() as cur:  # start an entry cursor
                print(f'INFO: Connection established to PS database on version: {con.version}')
                print(f'INFO: Connection established to PS database on version: {con.version}', file=log)

                # Start by getting a list of schools from the schools table view to get the school names, numbers, etc for use. If the mode is "full" we want all schools, if not we only want the main schools not excluded from state reporting
                if school_mode == 'full':  # do every school in PS
                    cur.execute('SELECT name, school_number, abbreviation FROM schools ORDER BY school_number')
                elif school_mode == 'limited':  # do only schools that would be in state reporting, aka "real" schools, not the graduated students, pre-registered, etc
                    cur.execute('SELECT name, school_number, abbreviation FROM schools WHERE State_ExcludeFromReporting = 0 ORDER BY school_number')
                else:  # otherwise do the specific school number that it could be called with
                    cur.execute('SELECT name, school_number, abbreviation FROM schools WHERE school_number = :school ORDER BY school_number', school = school_mode)

                schools = cur.fetchall()  # store all the query results in the schools list
                for school in schools:
                    # store results in variables mostly just for readability
                    schoolName = school[0].title()  # convert to title case since some are all caps
                    schoolNum = school[1]
                    schoolAbbrev = school[2]
                    # construct the string for the organization unit in Google Admin from the building name + students
                    orgUnit = OU_PREFIX + schoolAbbrev + ' Students'
                    if schoolName == GRADUATED_SCHOOL_NAME:  # check and see if our building is the graduated students building or enroll status is graduated since they have a different OU then the rest
                        orgUnit = GRADUATED_OU
                    print(f'DBUG: Starting Building: {schoolName} | {schoolNum} | {orgUnit}')  # debug
                    print(f'DBUG: Starting Building: {schoolName} | {schoolNum} | {orgUnit}',file=log)  # debug

                    # query for all students in the curent school
                    cur.execute('SELECT student_number, first_name, last_name, classof, enroll_status, schoolid, grade_level FROM students WHERE schoolid = :school ORDER BY student_number DESC', school=schoolNum)
                    students = cur.fetchall()
                    for student in students:
                        try:
                            bodyDict = {}  # define empty dict that will hold the update parameters
                            # print(student)
                            # print(student, file=log)
                            stuNum = int(student[0])
                            firstName = str(student[1]).title()
                            lastName = str(student[2]).title()
                            if firstName.lower() in BAD_NAMES or lastName.lower() in BAD_NAMES:  # check their first and last names against the list of test/dummy accounts
                                raise BadNameExceptionError('Found name that matches list of bad names')  # raise an exception for them if they have a bad name, which skips the rest of processing
                            email = str(stuNum) + EMAIL_SUFFIX
                            gradYear = int(student[3])
                            enroll = int(student[4])
                            school = int(student[5])
                            grade = int(student[6])

                            currentYear = int(startDate.strftime("%Y"))  # get the current year as a integer from the start time
                            currentMonth = startDate.strftime("%B")  # get the current month name as a string

                            suspended = False if enroll == 0 or enroll == -1 else True  # create a flag for whether they should be suspended or not, will be based on their enroll status
                            # override graduated students being suspended for the months of july and august so they can still access their emails until september 1st
                            if gradYear == currentYear and GRADUATED_ACTIVE_SUMMER:  # check current year against grad year
                                if currentMonth == "June" or currentMonth == "July" or currentMonth == "August":  # check if it is currently July or August
                                    if schoolName == GRADUATED_SCHOOL_NAME and enroll == 3:  # make sure the student is in the graduated students building and status of graduated
                                        suspended = False
                                        print(f'WARN: {email} is a {currentYear} graduate, they will remain active until September 1st')
                                        print(f'WARN: {email} is a {currentYear} graduate, they will remain active until September 1st', file=log)


                            # set the OU path based on their school, grades, enroll status, etc
                            properOU = orgUnit + GRADE_OUS.get(grade)  # for enabled accounts at normal buildings, they get the overall building OU + the grade level sub-OU
                            # have a section to set OU for pre registered and graduated students separately as it does not include any grade sub-ous
                            if school == 999999 or enroll == 3 or school == 901 or enroll == -1:
                                properOU = orgUnit
                            # if they are just suspended (but not graduated), they get the normal suspended OU
                            if suspended and (school != 999999 and enroll != 3):
                                properOU = SUSPENDED_OU


                            print(f'DBUG: User {email}, Name: {firstName} {lastName}, school: {school}, grade: {grade}, graduation year: {gradYear}, enroll: {enroll}, suspended: {suspended}, OU path: {properOU}')
                            print(f'DBUG: User {email}, Name: {firstName} {lastName}, school: {school}, grade: {grade}, graduation year: {gradYear}, enroll: {enroll}, suspended: {suspended}, OU path: {properOU}', file=log)

                            # next do a query in Google Admin for the students account based on their email
                            queryString = 'email=' + email  # construct the query string which looks for the email
                            userToUpdate = service.users().list(customer='my_customer', domain=GOOGLE_DOMAIN, maxResults=2, orderBy='email', projection='full', query=queryString).execute()  # return a list of at most 2 users

                            # process all the active students
                            if not suspended:
                                # print('enabled')
                                # print('enabled', file=log)
                                if userToUpdate.get('users'):  # if we found a user in Google that matches the user email, they already exist and we just want to update any info
                                    frozen = False  # define a flag for whether they are in a frozen OU, set to false initially

                                    # get info from their account
                                    currentlySuspended = userToUpdate.get('users')[0].get('suspended')
                                    currentOU = userToUpdate.get('users')[0].get('orgUnitPath')
                                    # print(f'DBUG: Student {email} already has an existing Google account, updating any info')
                                    # print(f'DBUG: Student {email} already has an existing Google account, updating any info', file=log)

                                    # check to see if the user is enabled in Google, if not add that to the update body
                                    if currentlySuspended == True:
                                        bodyDict.update({'suspended': False})

                                    # Check to see if they are in the correct OU (which is based on home building assignment)
                                    if currentOU != properOU:
                                        for org in FROZEN_OUS:  # go through our list of "frozen" OU paths which contain a few users with custom settings, licenses, etc
                                            if org in currentOU:  # check and see if the frozen OU path is part of the OU they are currently in, if so set the frozen flag to True
                                                frozen = True
                                        if frozen:  # if they are in a frozen OU we do not add the change, but just print out an info line for logging
                                            print(f'WARN: User {email} is in the frozen OU {currentOU} and will not be moved to {properOU}')
                                            print(f'WARN: User {email} is in the frozen OU {currentOU} and will not be moved to {properOU}', file=log)
                                        else:  # if theyre not in a frozen OU they will have the orgunit change added to the body of the update
                                            print(f'INFO: User {email} not in a frozen OU, will to be moved from {currentOU} to {properOU}')
                                            print(f'INFO: User {email} not in a frozen OU, will to be moved from {currentOU} to {properOU}', file=log)
                                            bodyDict.update({'orgUnitPath' : properOU})  # add OU to body of the update

                                    # Check to see if the student's name has changed significantly, if so update the name in Google
                                    currentFirstName = userToUpdate.get('users')[0].get('name').get('givenName')
                                    currentLastName = userToUpdate.get('users')[0].get('name').get('familyName')
                                    if currentFirstName.upper() != firstName.upper():
                                        print(f'INFO: User {email} has changed first name from {currentFirstName} to {firstName}, updating')
                                        print(f'INFO: User {email} has changed first name from {currentFirstName} to {firstName}, updating', file=log)
                                        bodyDict.update({'name' : {'givenName' : firstName}})
                                    if currentLastName.upper() != lastName.upper():
                                        print(f'INFO: User {email} has changed last name from {currentLastName} to {lastName}, updating')
                                        print(f'INFO: User {email} has changed last name from {currentLastName} to {lastName}, updating', file=log)
                                        bodyDict.update({'name' : {'familyName' : lastName}})

                                    # get custom attributes info from their google profile
                                    try:  # put the retrieval of the custom data in a try/except block because some accounts might not have the data, which will then need to be added
                                        currentSchool = int(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_CATEGORY).get(CUSTOM_ATTRIBUTE_SCHOOL))  # take the first user's custom schema homeschool id and store it
                                        currentGrad = int(userToUpdate.get('users')[0].get('customSchemas').get(CUSTOM_ATTRIBUTE_CATEGORY).get(CUSTOM_ATTRIBUTE_GRADYEAR))  # take the first user's custom schema graduation year and store it
                                        if (currentSchool != school or currentGrad != gradYear):
                                            print(f'INFO: Updating {email}. School from {currentSchool} to {school}, Graduation Year from {currentGrad} to {gradYear}')
                                            print(f'INFO: Updating {email}. School from {currentSchool} to {school}, Graduation Year from {currentGrad} to {gradYear}', file=log)
                                            bodyDict.update({'customSchemas' : {CUSTOM_ATTRIBUTE_CATEGORY : {CUSTOM_ATTRIBUTE_SCHOOL : school, CUSTOM_ATTRIBUTE_GRADYEAR : gradYear}}})
                                    except Exception as er:
                                        print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})')
                                        print(f'ERROR: User {email} had no or was missing Synchronization_Data, it will be created: ({er})', file=log)
                                        # Since the error was probably not having any synchronization data for whatever reason, it should be added to the body of the update
                                        print(f'INFO: Updating {email}. School to {school}, Graduation Year to {gradYear}')
                                        print(f'INFO: Updating {email}. School to {school}, Graduation Year to {gradYear}', file=log)
                                        bodyDict.update({'customSchemas' : {CUSTOM_ATTRIBUTE_CATEGORY : {CUSTOM_ATTRIBUTE_SCHOOL : school, CUSTOM_ATTRIBUTE_GRADYEAR : gradYear}}})

                                    # Finally, do the actual update of the user profile, using the bodyDict we have constructed in the above sections
                                    if bodyDict:  # if there is anything in the body dict we want to update. if its empty we skip the update
                                        try:
                                            print(bodyDict)  # debug
                                            print(bodyDict, file=log)  # debug
                                            outcome = service.users().update(userKey = email, body=bodyDict).execute()  # does the actual updating of the user profile
                                            # print(outcome, file=log)  # debug, should return the update json body
                                        except Exception as er:
                                            print(f'ERROR: cannot update {email} : {er}')
                                            print(f'ERROR: cannot update {email} : {er}', file=log)
                                # if there is no google result for our email query, we should try to create a new email account
                                else:
                                    print(f'INFO: User {email} does not exist, will be created')
                                    print(f'INFO: User {email} does not exist, will be created', file=log)
                                    try:
                                        # define the new user email, name, and all the basic fields
                                        newUser = {'primaryEmail' : email, 'name' : {'givenName' : firstName, 'familyName' : lastName}, 'password' : NEW_PASSWORD, 'changePasswordAtNextLogin' : True, 'orgUnitPath' : properOU,
                                                'customSchemas' : {CUSTOM_ATTRIBUTE_CATEGORY : {CUSTOM_ATTRIBUTE_SCHOOL : school, CUSTOM_ATTRIBUTE_GRADYEAR : gradYear}}}
                                        outcome = service.users().insert(body=newUser).execute()  # does the actual account creation
                                        # print(outcome, file=log)  # debug, should return the update json body
                                    except Exception as er:
                                        print(f'ERROR on user account creation for {email}: {er}')
                                        print(f'ERROR on user account creation for {email}: {er}', file=log)

                            # process all the inactive students
                            else:
                                # print(f'DBUG: User {email} is inactive, should be suspended')
                                # print(f'DBUG: User {email} is inactive, should be suspended', file=log)
                                if userToUpdate.get('users'):  # if we found a user in Google that matches the user email, they already exist and we just want to update any info
                                    # get info from their account
                                    currentlySuspended = userToUpdate.get('users')[0].get('suspended')
                                    currentOU = userToUpdate.get('users')[0].get('orgUnitPath')
                                    if not currentlySuspended:
                                        print(f'INFO: Suspending {email}')
                                        print(f'INFO: Suspending {email}', file=log)
                                        bodyDict.update({'suspended' : True})  # add the suspended: True to the body of the update patch
                                    if currentOU != properOU:
                                        print(f'INFO: Moving {email} to suspended OU {properOU}')
                                        print(f'INFO: Moving {email} to suspended OU {properOU}', file=log)
                                        bodyDict.update({'orgUnitPath' : properOU})  # add the suspended OU to the org unit path for the update patch

                                    # finally do the update (suspend and move) if we have anything in the bodyDict
                                    if bodyDict:
                                        print(bodyDict)
                                        print(bodyDict, file=log)
                                        outcome = service.users().update(userKey = email, body=bodyDict).execute()  # does the actual updating of the user profile  # noqa: F841
                                        # print(outcome, file=log)  # debug, should return the update json body
                                        # Remove the newly suspended user from any groups they were a member of
                                        userGroups = service.groups().list(userKey=email).execute().get('groups')  # get the current groups the user is in
                                        if userGroups:
                                            for group in userGroups:  # if they have groups they are still a member of, go through each group and remove them
                                                name = group.get('name')
                                                groupEmail = group.get('email')
                                                print(f'{email} was a member of: {name} - {groupEmail}, they will be removed from the group')
                                                print(f'{email} was a member of: {name} - {groupEmail}, they will be removed from the group',file=log)
                                                service.members().delete(groupKey=groupEmail, memberKey=email).execute()
                                        else:
                                            print(f'DBUG: Newly suspended account {email} was not in any groups, no removal needed')
                                            print(f'DBUG: Newly suspended account {email} was not in any groups, no removal needed', file=log)
                                    # else:  # handles if they were already suspended and no change needed
                                        # print(f'DBUG: {email} is already suspended in the correct suspended accounts OU, no update needed')
                                        # print(f'DBUG: {email} is already suspended in the correct suspended accounts OU, no update needed', file=log)
                                # else:  # if we did not find any google accounts matching the email, just give a warning
                                    # print(f'DBUG: Found inactive student {email} without Google account that matches.')
                                    # print(f'DBUG: Found inactive student {email} without Google account that matches.', file=log)

                        except BadNameExceptionError:
                            print(f'WARN: found user matching name in bad names list {email} - {firstName} {lastName}')
                            print(f'WARN: found user matching name in bad names list {email} - {firstName} {lastName}', file=log)
                        except HttpError as er:   # catch Google API http errors, get the specific message and reason from them for better logging
                            status = er.status_code
                            details = er.error_details[0]  # error_details returns a list with a dict inside of it, just strip it to the first dict
                            print(f'ERROR {status} from Google API while processing student {student[0]}: {details["message"]}. Reason: {details["reason"]}')
                            print(f'ERROR {status} from Google API while processing student {student[0]}: {details["message"]}. Reason: {details["reason"]}', file=log)
                        except Exception as er:
                            print(f'ERROR while processing student {student[0]}: {er}')
                            print(f'ERROR while processing student {student[0]}: {er}', file=log)

        endTime = datetime.now()
        endTime = endTime.strftime('%H:%M:%S')
        print(f'Execution ended at {endTime}')
        print(f'Execution ended at {endTime}', file=log)

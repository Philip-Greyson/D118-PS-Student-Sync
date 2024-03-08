# # D118-PS-Student-Sync

Scripts to synchronize student data from PowerSchool to Google profiles.

## Overview

This project consists of one main script and a few helper scripts that really just call the main script with different arguments, so that it can be used in task scheduler or other scheduled jobs. The main script can either be called to process every building in PowerSchool, only those that are included in state reporting, or a specific building number.
The main script does a SQL query to PowerSchool for all students in whichever buildings are in the scope, and then each student is iterated through one at a time. Each student email is then queried through the Google Admin directory API, and their current information is retrieved. If a student who is active (not suspended or graduated) in PowerSchool is not found in Google, an account is created for them. If they are not active in PowerSchool, their account is moved to specific suspended or graduated organizational units in Google, and their account is disabled. For active PowerSchool accounts with matching Google profile, we make sure they are in the correct Google organizational unit, and have the correct information in their profile including name and custom attributes for their school and graduation year. It also can check a list of organizational units and not move accounts that are in them out so that specific students can be left in non-standard organizational units for special policies, apps, or licensing.
The process is currently pretty slow since we do individual Google API queries for each student, it would probably be much faster (though RAM intensive) to get all users in our normal student and suspended/graduated OUs at the same time and store their data in a dictionary for quick reference.

## Requirements

The following Environment Variables must be set on the machine running the script:

- POWERSCHOOL_READ_USER
- POWERSCHOOL_DB_PASSWORD
- POWERSCHOOL_PROD_DB
- NEW_USER_PASSWORD

These are fairly self explanatory, and just relate to the usernames, passwords, and host IP/URLs for PowerSchool, and then the password that is used on new account creation in Google (see customization below). If you wish to directly edit the script and include these credentials or to use other environment variable names, you can.

Additionally, the following Python libraries must be installed on the host machine (links to the installation guide):

- [Python-oracledb](https://python-oracledb.readthedocs.io/en/latest/user_guide/installation.html)
- [Python-Google-API](https://github.com/googleapis/google-api-python-client#installation)

In addition, an OAuth credentials.json file must be in the same directory as the overall script. This is the credentials file you can download from the Google Cloud Developer Console under APIs & Services > Credentials > OAuth 2.0 Client IDs. Download the file and rename it to credentials.json. When the program runs for the first time, it will open a web browser and prompt you to sign into a Google account that has the permissions to disable, enable, deprovision, and move the devices. Based on this login it will generate a token.json file that is used for authorization. When the token expires it should auto-renew unless you end the authorization on the account or delete the credentials from the Google Cloud Developer Console. One credentials.json file can be shared across multiple similar scripts if desired.
There are full tutorials on getting these credentials from scratch available online. But as a quickstart, you will need to create a new project in the Google Cloud Developer Console, and follow [these](https://developers.google.com/workspace/guides/create-credentials#desktop-app) instructions to get the OAuth credentials, and then enable APIs in the project (the Admin SDK API is used in this project).

Finally, in Google Admin, you must create custom attributes to store the homeschool ID and graduation year fields. This can be done from Directory > Users > More Options > Manage Custom Attributes. You can create a new category or use an existing one if you have other custom attributes, but both fields should be in the same category.
Take the names of the category and field name and set the `CUSTOM_ATTRIBUTE_CATEGORY`, `CUSTOM_ATTRIBUTE_SCHOOL` and `CUSTOM_ATTRIBUTE_GRADYEAR` constants in the main script to match them.
If there are spaces, or you made an attribute, deleted it and then made a new one with the same name, the names can sometimes not match what they are actually called internally in Google. To see all the custom attributes for a user, you can use `print( user.get('customSchemas', {}))` inside a user query that includes `projection = full` and it will show all their custom attribute category and field names, which you can then use to plug into the constants.

## Customization

This script is an extremely customized for our specific use case at D118. I have done my best to break out specific organizational units (OUs) and things to constants which you can change at the top of the main script, see below for what you will want to change and why.

**However, there are some assumptions the script makes due to how our organizational units (OUs) are organized.** If you do not have a similar structure you will likely need to overhaul large parts of the script to get them to work. We have an overall students OU, then within that each building has an OU constructed from the abbreviation of the school plus the word "Students" (i.e. if the school abbreviation was XYZ the OU would be "XYZ Students"). Then each school has relevant grade level OUs under it where the students are actually placed in, so that each grade level could have different policies. The exception to this is for graduated or suspended students, which are placed in their own top-level OUs.

- As discussed in the requirements section, `CUSTOM_ATTRIBUTE_CATEGORY`, `CUSTOM_ATTRIBUTE_SCHOOL` and `CUSTOM_ATTRIBUTE_GRADYEAR` should match the names of the custom attributes in Google Admin.
- `EMAIL_SUFFIX` should be pretty self explanatory, it is the domain for your emails. If you use a different email structure than we do, you will need to edit the `email =  str(stuNum) + EMAIL_SUFFIX` line to change how its constructed.
- `OU_PREFIX` is the overall umbrella organization unit name for students. It is used as the prefix before the school and grade specific OUs.
- If you need to construct the building OUs differently, you will need to edit the `orgUnit = OU_PREFIX + schoolAbbrev +  ' Students'` line to fit your needs.
- `GRADE_OUS` is a dictionary mapping the grade level integers to the string names of the grade level sub-OUs inside each building OU. If you have different names for those OUs (for example spelling out Second instead of 2nd) you will want to edit the dictionary to have the correct mappings.
  - If you don't have grade specific sub-OUs, you can edit the `properOU = orgUnit + GRADE_OUS.get(grade)` line and omit the concatenation of the grades completely, this should place all the students just in the building level OU.
- As discussed above, suspended and graduated students are placed directly in the `SUSPENDED_OU` and `GRADUATED_OU` OUs directly, so they should be changed to the relevant OU for storing those accounts (they can be the same OU if desired).
  - We have a graduated student building in PowerSchool where students are placed though sometimes their enroll status is not set correctly to graduated, so I also check the school name directly to tell if they should be graduated. `GRADUATED_SCHOOL_NAME` is the full name of the building in PowerSchool that can tell if they are a graduated student. ou can edit the line `if schoolName == GRADUATED_SCHOOL_NAME or enroll ==  3:` to only include the enroll == 3 to check purely by enroll_status.
- `FROZEN_OUS` is the list of suffixes that an OU will have when you do not want students to be moved out of it by this script. For example, we have specific students that need extra locked down policies and apps, so by including `"/Restricted"` any OUs that are named that in their respective buildings will be ignored by the moving part of this script.
- `NEW_PASSWORD` is the password that is assigned to new student accounts that are created through this script. You should change it to be relevant to your district, we have a generic one that is then overwritten with other scripts once the students start.
- We keep graduated student accounts active until September 1st after they graduate (~2 months after they are marked graduated in PowerSchool). `GRADUATED_ACTIVE_SUMMER` is a True/False boolean describing whether this should happen for your district, though it assumes the rollover will happen in June, July, or August.
- Finally, if you have test accounts you don't want to be processed by the script (or need to skip over specific students for some reason), you can use the `BAD_NAMES` list to skip anyone who matches their lowercase first or last name to a name in the list.

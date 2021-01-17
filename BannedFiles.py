#!/usr/bin/env python3

##############################################################################
### NZBGET QUEUE/POST-PROCESSING SCRIPT                                    ###
### QUEUE EVENTS: NZB_ADDED, NZB_DOWNLOADED, FILE_DOWNLOADED

# Detect nzbs with unwanted extensions.
#
# If a file with an unwanted extension is detected the download is marked as bad. NZBGet removes
# the download from queue and (if option "DeleteCleanupDisk" is active) the
# downloaded files are deleted from disk. If duplicate handling is active
# (option "DupeCheck") then another duplicate is chosen for download
# if available.
#
# The status "FAILURE/BAD" is passed to other scripts and informs them
# about failure.
#
#
# NOTE: This script requires Python to be installed on your system (tested
# only with Python 3.x).


##############################################################################
### OPTIONS                                                                ###

# Banned extensions.
#
# Downloads which contain files with any of the following extensions will be marked as unwanted.
# Extensions must be separated by a comma (eg: .wmv, .divx).
#BannedExtensions=


### NZBGET QUEUE/POST-PROCESSING SCRIPT                                    ###
##############################################################################

import os
import sys
import subprocess
import re
import urllib.request, urllib.error, urllib.parse
from xmlrpc.client import ServerProxy
from base64 import b64encode
import shlex
import traceback

# Exit codes used by NZBGet for post-processing scripts.
# Queue-scripts don't have any special exit codes.
POSTPROCESS_SUCCESS=93
POSTPROCESS_NONE=95
POSTPROCESS_ERROR=94

mediaExtensions = ['.mkv', '.avi', '.divx', '.xvid', '.mov', '.wmv', '.mp4', '.mpg', '.mpeg', '.vob', '.iso', '.m4v']
bannedExtensions = os.environ.get('NZBPO_BANNEDEXTENSIONS', '').replace(' ', '').split(',')


# NZBPR_PPSTATUS_BANNED: boolean, true if found unwanted extension
# NZBPR_PPSTATUS_BANNEDFILE: list of banned files

def startCheck():
    # Check if the script is called from a compatible NZBGet version (as queue-script or as pp-script)
    if not ('NZBNA_EVENT' in os.environ or 'NZBPP_DIRECTORY' in os.environ) or not 'NZBOP_ARTICLECACHE' in os.environ:
        print('*** NZBGet queue script ***')
        print('This script is supposed to be called from nzbget (14.0 or later).')
        sys.exit(1)

    # This script processes only certain queue events.
    # For compatibility with newer NZBGet versions it ignores event types it doesn't know
    if os.environ.get('NZBNA_EVENT') not in ['NZB_ADDED', 'FILE_DOWNLOADED', 'NZB_DOWNLOADED', None]:
        sys.exit(0)

    # If nzb was already marked as bad don't do any further detection
    if os.environ.get('NZBPP_STATUS') == 'FAILURE/BAD':
        if os.environ.get('NZBPR_PPSTATUS_BANNED') == 'yes':
            # Print the message again during post-processing to add it into the post-processing log
            # (which is then can be used by notification scripts such as EMail.py)
            # Pp-parameter "NZBPR_PPSTATUS_BANNEDFILE" contains more details (saved previously by our script)
            print('[WARNING] Download contains banned extension ' + os.environ.get('NZBPR_PPSTATUS_BANNEDFILE'))
        cleanUp()
        sys.exit(POSTPROCESS_SUCCESS)

    # If called via "Post-process again" from history details dialog the download may not exist anymore
    if 'NZBPP_DIRECTORY' in os.environ and not os.path.exists(os.environ.get('NZBPP_DIRECTORY')):
        print('Destination directory doesn\'t exist, exiting')
        cleanUp()
        sys.exit(POSTPROCESS_NONE)

    # If nzb is already failed, don't do any further detection
    if os.environ.get('NZBPP_TOTALSTATUS') == 'FAILURE':
        cleanUp()
        sys.exit(POSTPROCESS_NONE)

def cleanUp():
    nzb_id = os.environ.get('NZBPP_NZBID')
    temp_folder = os.environ.get('NZBOP_TEMPDIR') + '/BannedFiles'

    nzbids = []
    files = os.listdir(temp_folder)

    if len(files) > 1:
        # Create the list of nzbs in download queue
        data = callNzbget('listgroups?1=0')
        # The "data" is a raw json-string. We could use json.loads(data) to
        # parse it but json-module is slow. We parse it on our own.
        for line in data.splitlines():
            if line.startswith('"NZBID" : '):
                cur_id = int(line[10:len(line)-1])
                nzbids.append(str(cur_id))

    old_temp_files = list(set(files)-set(nzbids))
    if nzb_id in files and nzb_id not in old_temp_files:
        old_temp_files.append(nzb_id)

    for temp_id in old_temp_files:
        temp_file = temp_folder + '/' + str(temp_id)
        try:
            print('[DETAIL] Removing temp file ' + temp_file)
            os.remove(temp_file)
        except:
            print('[ERROR] Could not remove temp file ' + temp_file)

def callNzbget(url_command):
    # First we need to know connection info: host, port and password of NZBGet server.
    # NZBGet passes all configuration options to scripts as environment variables.
    host = os.environ['NZBOP_CONTROLIP']
    if host == '0.0.0.0': host = '127.0.0.1'
    port = os.environ['NZBOP_CONTROLPORT']
    username = os.environ['NZBOP_CONTROLUSERNAME']
    password = os.environ['NZBOP_CONTROLPASSWORD']

    # Building http-URL to call the method
    httpUrl = 'http://%s:%s/jsonrpc/%s' % (host, port, url_command)
    request = urllib.request.Request(httpUrl)

    authString = '%s:%s' % (username, password)
    base64string = b64encode(authString.encode()).decode("ascii")

    request.add_header("Authorization", "Basic %s" % base64string)

    # Load data from NZBGet
    response = urllib.request.urlopen(request)
    data = response.read().decode('utf-8')

    # "data" is a JSON raw-string
    return data

def connectNzbget():
    # First we need to know connection info: host, port and password of NZBGet server.
    # NZBGet passes all configuration options to scripts as environment variables.
    host = os.environ['NZBOP_CONTROLIP']
    if host == '0.0.0.0': host = '127.0.0.1'
    port = os.environ['NZBOP_CONTROLPORT']
    username = os.environ['NZBOP_CONTROLUSERNAME']
    password = os.environ['NZBOP_CONTROLPASSWORD']

    # Build an URL for XML-RPC requests
    # TODO: encode username and password in URL-format
    xmlRpcUrl = 'http://%s:%s@%s:%s/xmlrpc' % (username, password, host, port)

    # Create remote server object
    nzbget = ServerProxy(xmlRpcUrl)
    return nzbget

def detectBannedFile(dir):
    fileList = [ o for o in os.listdir(dir) if os.path.isfile(os.path.join(dir, o)) ]
    for item in fileList:
        if os.path.splitext(item)[-1] in bannedExtensions:
            print('[INFO] Found file with banned extension: ' + item)
            print('[NZB] NZBPR_PPSTATUS_BANNEDFILE=%s' % item)
            return item
    return None

def sort_inner_files():
    nzb_id = int(os.environ.get('NZBNA_NZBID'))

    # Building command-URL to call method "listfiles" passing three parameters: (0, 0, nzb_id)
    url_command = 'listfiles?1=0&2=0&3=%i' % nzb_id
    data = callNzbget(url_command)

    # The "data" is a raw json-string. We could use json.loads(data) to
    # parse it but json-module is slow. We parse it on our own.

    # Iterate through the list of files to find the last rar-file.
    # The last is the one with the highest XX in ".partXX.rar" or ".rXX"
    regex1 = re.compile(r'.*\.part(\d+)\.rar', re.IGNORECASE)
    regex2 = re.compile(r'.*\.r(\d+)', re.IGNORECASE)
    file_num = None
    file_id = None
    file_name = None

    for line in data.splitlines():
        if line.startswith('"ID" : '):
            cur_id = int(line[7:len(line)-1])
        if line.startswith('"Filename" : "'):
            cur_name = line[14:len(line)-2]
            match = regex1.match(cur_name) or regex2.match(cur_name)
            if (match):
                cur_num = int(match.group(1))
                if not file_num or cur_num > file_num:
                    file_num = cur_num
                    file_id = cur_id
                    file_name = cur_name

    # Move the last rar-file to the top of file list
    if (file_id):
        print('[INFO] Moving last rar-file to the top: %s' % file_name)
        # Create remote server object
        nzbget = connectNzbget()
        # Using RPC-method "editqueue" of XML-RPC-object "nzbget".
        # we could use direct http access here too but the speed isn't
        # an issue here and XML-RPC is easier to use.
        nzbget.editqueue('FileMoveTop', 0, '', [file_id])
    else:
        print('[INFO] Skipping sorting since could not find any rar-files')

def main():
    startCheck()

    # Set prefix if post processing or downloading
    Prefix = 'NZBNA_' if 'NZBNA_EVENT' in os.environ else 'NZBPP_'

    # Read context (what nzb is currently being processed)
    # Category = os.environ[Prefix + 'CATEGORY']
    Directory = os.environ[Prefix + 'DIRECTORY']
    NzbName = os.environ[Prefix + 'NZBNAME']

    # Directory for storing list of tested files
    # tmp_file_name = os.environ.get('NZBOP_TEMPDIR') + '/BannedFiles/' + os.environ.get(Prefix + 'NZBID')


    # When nzb is added to queue - reorder inner files for earlier fake detection.
    # Also it is possible that nzb was added with a category which doesn't have
    # FakeDetector listed in the PostScript. In this case FakeDetector was not called
    # when adding nzb to queue but it is being called now and we can reorder
    # files now.
    if os.environ.get('NZBNA_EVENT') == 'NZB_ADDED' or \
            (os.environ.get('NZBNA_EVENT') == 'FILE_DOWNLOADED' and \
            os.environ.get('NZBPR_BANNEDFILES_SORTED') != 'yes'):
        print('[INFO] Sorting inner files for earlier file detection in %s' % NzbName)
        sys.stdout.flush()
        sort_inner_files()
        print('[NZB] NZBPR_BANNEDFILES_SORTED=yes')
        if os.environ.get('NZBNA_EVENT') == 'NZB_ADDED':
            sys.exit(POSTPROCESS_NONE)

    print('[INFO] Detecting banned files in %s' % NzbName)
    sys.stdout.flush()

    if detectBannedFile(Directory):
        # A banned file is detected
        #
        # Add post-processing parameter "PPSTATUS_FAKE" for nzb-file.
        # Scripts running after fake detector can check the parameter like this:
        # if os.environ.get('NZBPR_PPSTATUS_FAKE') == 'yes':
        #     print('Marked as fake by another script')
        print('[NZB] NZBPR_PPSTATUS_BANNED=yes')

        # Special command telling NZBGet to mark nzb as bad. The nzb will
        # be removed from queue and become status "FAILURE/BAD".
        print('[NZB] MARK=BAD')
    else:
        # Not a fake or at least doesn't look like a fake (yet).
        #
        # When nzb is downloaded again (using "Download again" from history)
        # it may have been marked by our script as a fake. Since now the script
        # doesn't consider nzb as fake we remove the old marking. That's
        # of course a rare case that someone will redownload a fake but
        # at least during debugging of fake detector we do that all the time.
        print('[INFO] No Banned files detected in %s yet' % NzbName)
        if os.environ.get('NZBPR_PPSTATUS_BANNED') == 'yes':
            print('[NZB] NZBPR_PPSTATUS_BANNED=')

    print('[DETAIL] Detecting banned files completed for %s' % NzbName)
    sys.stdout.flush()

    # Remove temp files in PP
    if Prefix == 'NZBPP_':
        cleanUp()

main()

# Everything completed successfully 
sys.exit(POSTPROCESS_SUCCESS)
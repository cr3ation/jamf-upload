#!/usr/local/autopkg/python

"""
JamfScriptUploader processor for uploading items to Jamf Pro using AutoPkg
    by G Pugh
"""

import json
import re
import os.path
import subprocess
import uuid

from base64 import b64encode
from collections import namedtuple
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from time import sleep
from urllib.parse import quote
from xml.sax.saxutils import escape
from autopkglib import Processor, ProcessorError  # pylint: disable=import-error


class JamfScriptUploader(Processor):
    """A processor for AutoPkg that will upload a script to a Jamf Cloud or on-prem server."""

    input_variables = {
        "JSS_URL": {
            "required": True,
            "description": "URL to a Jamf Pro server that the API user has write access "
            "to, optionally set as a key in the com.github.autopkg "
            "preference file.",
        },
        "API_USERNAME": {
            "required": True,
            "description": "Username of account with appropriate access to "
            "jss, optionally set as a key in the com.github.autopkg "
            "preference file.",
        },
        "API_PASSWORD": {
            "required": True,
            "description": "Password of api user, optionally set as a key in "
            "the com.github.autopkg preference file.",
        },
        "script_path": {
            "required": False,
            "description": "Full path to the script to be uploaded",
        },
        "script_name": {
            "required": False,
            "description": "Name of the script in Jamf",
        },
        "script_category": {
            "required": False,
            "description": "Script category",
            "default": "",
        },
        "script_priority": {
            "required": False,
            "description": "Script priority (BEFORE or AFTER)",
            "default": "AFTER",
        },
        "osrequirements": {
            "required": False,
            "description": "Script OS requirements",
            "default": "",
        },
        "script_info": {
            "required": False,
            "description": "Script info field",
            "default": "",
        },
        "script_notes": {
            "required": False,
            "description": "Script notes field",
            "default": "",
        },
        "script_parameter4": {
            "required": False,
            "description": "Script parameter 4 title",
            "default": "",
        },
        "script_parameter5": {
            "required": False,
            "description": "Script parameter 5 title",
            "default": "",
        },
        "script_parameter6": {
            "required": False,
            "description": "Script parameter 6 title",
            "default": "",
        },
        "script_parameter7": {
            "required": False,
            "description": "Script parameter 7 title",
            "default": "",
        },
        "script_parameter8": {
            "required": False,
            "description": "Script parameter 8 title",
            "default": "",
        },
        "script_parameter9": {
            "required": False,
            "description": "Script parameter 9 title",
            "default": "",
        },
        "script_parameter10": {
            "required": False,
            "description": "Script parameter 10 title",
            "default": "",
        },
        "script_parameter11": {
            "required": False,
            "description": "Script parameter 11 title",
            "default": "",
        },
        "replace_script": {
            "required": False,
            "description": "Overwrite an existing category if True.",
            "default": False,
        },
    }

    output_variables = {
        "script_name": {
            "required": False,
            "description": "Name of the uploaded script",
        },
        "jamfscriptuploader_summary_result": {
            "description": "Description of interesting results.",
        },
    }

    # do not edit directly - copy from template
    def api_endpoints(self, object_type):
        """Return the endpoint URL from the object type"""
        api_endpoints = {
            "category": "api/v1/categories",
            "extension_attribute": "JSSResource/computerextensionattributes",
            "computer_group": "JSSResource/computergroups",
            "jamf_pro_version": "api/v1/jamf-pro-version",
            "package": "JSSResource/packages",
            "os_x_configuration_profile": "JSSResource/osxconfigurationprofiles",
            "policy": "JSSResource/policies",
            "policy_icon": "JSSResource/fileuploads/policies",
            "restricted_software": "JSSResource/restrictedsoftware",
            "script": "api/v1/scripts",
            "token": "api/v1/auth/token",
        }
        return api_endpoints[object_type]

    # do not edit directly - copy from template
    def object_list_types(self, object_type):
        """Return a XML dictionary type from the object type"""
        object_list_types = {
            "computer_group": "computer_groups",
            "extension_attribute": "computer_extension_attributes",
            "os_x_configuration_profile": "os_x_configuration_profiles",
            "package": "packages",
            "policy": "policies",
            "restricted_software": "restricted_software",
            "script": "scripts",
        }
        return object_list_types[object_type]

    # do not edit directly - copy from template
    def write_json_file(self, data, tmp_dir="/tmp/jamf_upload"):
        """dump some json to a temporary file"""
        self.make_tmp_dir(tmp_dir)
        tf = os.path.join(tmp_dir, f"jamf_upload_{str(uuid.uuid4())}.json")
        with open(tf, "w") as fp:
            json.dump(data, fp)
        return tf

    # do not edit directly - copy from template
    def write_temp_file(self, data, tmp_dir="/tmp/jamf_upload"):
        """dump some text to a temporary file"""
        self.make_tmp_dir(tmp_dir)
        tf = os.path.join(tmp_dir, f"jamf_upload_{str(uuid.uuid4())}.txt")
        with open(tf, "w") as fp:
            fp.write(data)
        return tf

    # do not edit directly - copy from template
    def make_tmp_dir(self, tmp_dir="/tmp/jamf_upload"):
        """make the tmp directory"""
        if not os.path.exists(tmp_dir):
            os.mkdir(tmp_dir)
        return tmp_dir

    # do not edit directly - copy from template
    def clear_tmp_dir(self, tmp_dir="/tmp/jamf_upload"):
        """remove the tmp directory"""
        if os.path.exists(tmp_dir):
            rmtree(tmp_dir)
        return tmp_dir

    # do not edit directly - copy from template
    def get_enc_creds(self, user, password):
        """encode the username and password into a b64-encoded string"""
        credentials = f"{self.jamf_user}:{self.jamf_password}"
        enc_creds_bytes = b64encode(credentials.encode("utf-8"))
        enc_creds = str(enc_creds_bytes, "utf-8")
        return enc_creds

    # do not edit directly - copy from template
    def check_api_token(self, token_file="/tmp/jamf_upload_token"):
        """Check validity of an existing token"""
        if os.path.exists(token_file):
            with open(token_file, "rb") as file:
                data = json.load(file)
                # check that there is a 'token' key
                if data["token"]:
                    # check if it's expired or not
                    expires = datetime.strptime(
                        data["expires"], "%Y-%m-%dT%H:%M:%S.%fZ"
                    )
                    if expires > datetime.utcnow():
                        self.output("Existing token is valid")
                        return data["token"]
                else:
                    self.output("Token not found in file", verbose_level=2)
        self.output("No existing valid token found", verbose_level=2)

    # do not edit directly - copy from template
    def write_token_to_json_file(self, data, token_file="/tmp/jamf_upload_token"):
        """dump the token and expiry as json to a temporary file"""
        with open(token_file, "w") as fp:
            json.dump(data, fp)

    # do not edit directly - copy from template
    def get_api_token(self, jamf_url, enc_creds):
        """get a token for the Jamf Pro API or Classic API for Jamf Pro 10.35+"""
        url = jamf_url + "/" + self.api_endpoints("token")
        r = self.curl(request="POST", url=url, enc_creds=enc_creds)
        if r.status_code == 200:
            try:
                self.output(r.output, verbose_level=2)
                token = str(r.output["token"])
                expires = str(r.output["expires"])

                # write the data to a file
                self.write_token_to_json_file(r.output)
                self.output("Session token received")
                self.output(f"Token: {token}", verbose_level=2)
                self.output(f"Expires: {expires}", verbose_level=2)
                return token
            except KeyError:
                self.output("ERROR: No token received in response")
        else:
            self.output(f"ERROR: No token received (response: {r.status_code})")

    # do not edit directly - copy from template
    def curl(
        self, request="", url="", token="", enc_creds="", data="", additional_headers=""
    ):
        """
        build a curl command based on method (GET, PUT, POST, DELETE)
        If the URL contains 'api' then token should be passed to the auth variable,
        otherwise the enc_creds variable should be passed to the auth variable
        """
        tmp_dir = self.make_tmp_dir()
        headers_file = os.path.join(tmp_dir, "curl_headers_from_jamf_upload.txt")
        output_file = os.path.join(tmp_dir, "curl_output_from_jamf_upload.txt")
        cookie_jar = os.path.join(tmp_dir, "curl_cookies_from_jamf_upload.txt")

        # build the curl command
        if url:
            curl_cmd = [
                "/usr/bin/curl",
                "--silent",
                "--show-error",
                "-D",
                headers_file,
                "--output",
                output_file,
                url,
            ]
        else:
            raise ProcessorError("No URL supplied")

        if request:
            curl_cmd.extend(["--request", request])

        # authorisation if using Jamf Pro API or Classic API
        # if using Jamf Pro API, or Classic API on Jamf Pro 10.35+,
        # and we already have a token, then we use the token for authorization.
        # The Slack webhook doesn't have authentication
        if token:
            curl_cmd.extend(["--header", f"authorization: Bearer {token}"])
        # basic auth to obtain a token, or for classic API older than 10.35
        elif enc_creds:
            curl_cmd.extend(["--header", f"authorization: Basic {enc_creds}"])

        # set either Accept or Content-Type depending on method
        if request == "GET" or request == "DELETE":
            curl_cmd.extend(["--header", "Accept: application/json"])
        # icon upload requires special method
        elif request == "POST" and "fileuploads" in url:
            curl_cmd.extend(["--header", "Content-type: multipart/form-data"])
            curl_cmd.extend(["--form", f"name=@{data}"])
        elif request == "POST" or request == "PUT":
            if data:
                if "slack" in url:
                    # slack requires data argument
                    curl_cmd.extend(["--data", data])
                else:
                    # jamf data upload requires upload-file argument
                    curl_cmd.extend(["--upload-file", data])
            # Jamf Pro API and Slack accepts json, but Classic API accepts xml
            if "JSSResource" in url:
                curl_cmd.extend(["--header", "Content-type: application/xml"])
            else:
                curl_cmd.extend(["--header", "Content-type: application/json"])
        else:
            self.output(f"WARNING: HTTP method {request} not supported")

        # write session for jamf requests
        if "/api/" in url or "JSSResource" in url or "dbfileupload" in url:
            try:
                with open(headers_file, "r") as file:
                    headers = file.readlines()
                existing_headers = [x.strip() for x in headers]
                for header in existing_headers:
                    if "APBALANCEID" in header or "AWSALB" in header:
                        with open(cookie_jar, "w") as fp:
                            fp.write(header)
            except IOError:
                pass

            # look for existing session
            try:
                with open(cookie_jar, "r") as file:
                    headers = file.readlines()
                existing_headers = [x.strip() for x in headers]
                for header in existing_headers:
                    if "APBALANCEID" in header or "AWSALB" in header:
                        cookie = header.split()[1].rstrip(";")
                        self.output(f"Existing cookie found: {cookie}", verbose_level=2)
                        curl_cmd.extend(["--cookie", cookie])
            except IOError:
                self.output(
                    "No existing cookie found - starting new session", verbose_level=2
                )

        # additional headers for advanced requests
        if additional_headers:
            curl_cmd.extend(additional_headers)

        self.output(f"curl command: {' '.join(curl_cmd)}", verbose_level=3)

        # now subprocess the curl command and build the r tuple which contains the
        # headers, status code and outputted data
        subprocess.check_output(curl_cmd)

        r = namedtuple(
            "r", ["headers", "status_code", "output"], defaults=(None, None, None)
        )
        try:
            with open(headers_file, "r") as file:
                headers = file.readlines()
            r.headers = [x.strip() for x in headers]
            for header in r.headers:  # pylint: disable=not-an-iterable
                if re.match(r"HTTP/(1.1|2)", header) and "Continue" not in header:
                    r.status_code = int(header.split()[1])
        except IOError:
            raise ProcessorError(f"WARNING: {headers_file} not found")
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, "rb") as file:
                if "/api/" in url:
                    r.output = json.load(file)
                else:
                    r.output = file.read()
        else:
            self.output(f"No output from request ({output_file} not found or empty)")
        return r()

    # do not edit directly - copy from template
    def status_check(self, r, endpoint_type, obj_name):
        """Return a message dependent on the HTTP response"""
        if r.status_code == 200 or r.status_code == 201:
            self.output(f"{endpoint_type} '{obj_name}' uploaded successfully")
            return "break"
        elif r.status_code == 409:
            self.output(r.output, verbose_level=2)
            raise ProcessorError(
                f"WARNING: {endpoint_type} '{obj_name}' upload failed due to a conflict"
            )
        elif r.status_code == 401:
            raise ProcessorError(
                f"ERROR: {endpoint_type} '{obj_name}' upload failed due to permissions error"
            )
        else:
            self.output(f"WARNING: {endpoint_type} '{obj_name}' upload failed")
            self.output(r.output, verbose_level=2)

    # do not edit directly - copy from template
    def get_uapi_obj_id_from_name(self, jamf_url, object_type, object_name, token):
        """Get the Jamf Pro API object by name. This requires use of RSQL filtering"""
        url_filter = f"?page=0&page-size=1000&sort=id&filter=name%3D%3D%22{quote(object_name)}%22"
        url = jamf_url + "/" + self.api_endpoints(object_type) + url_filter
        r = self.curl(request="GET", url=url, token=token)
        if r.status_code == 200:
            obj_id = 0
            for obj in r.output["results"]:
                self.output(f"ID: {obj['id']} NAME: {obj['name']}", verbose_level=3)
                if obj["name"] == object_name:
                    obj_id = obj["id"]
            return obj_id

    # do not edit directly - copy from template
    def substitute_assignable_keys(self, data, xml_escape=False):
        """substitutes any key in the inputted text using the %MY_KEY% nomenclature"""
        # do a four-pass to ensure that all keys are substituted
        loop = 5
        while loop > 0:
            loop = loop - 1
            found_keys = re.findall(r"\%\w+\%", data)
            if not found_keys:
                break
            found_keys = [i.replace("%", "") for i in found_keys]
            for found_key in found_keys:
                if self.env.get(found_key):
                    self.output(
                        (
                            f"Replacing any instances of '{found_key}' with",
                            f"'{str(self.env.get(found_key))}'",
                        ),
                        verbose_level=2,
                    )
                    if xml_escape:
                        replacement_key = escape(self.env.get(found_key))
                    else:
                        replacement_key = self.env.get(found_key)
                    data = data.replace(f"%{found_key}%", replacement_key)
                else:
                    self.output(
                        f"WARNING: '{found_key}' has no replacement object!",
                    )
                    raise ProcessorError("Unsubstitutable key in template found")
        return data

    # do not edit directly - copy from template
    def get_path_to_file(self, filename):
        """AutoPkg is not very good at finding dependent files. This function
        will look inside the search directories for any supplied file"""
        # if the supplied file is not a path, use the override directory or
        # recipe dir if no override
        recipe_dir = self.env.get("RECIPE_DIR")
        filepath = os.path.join(recipe_dir, filename)
        if os.path.exists(filepath):
            self.output(f"File found at: {filepath}")
            return filepath

        # if not found, search parent directories to look for it
        if self.env.get("PARENT_RECIPES"):
            # also look in the repos containing the parent recipes.
            parent_recipe_dirs = list(
                {os.path.dirname(item) for item in self.env["PARENT_RECIPES"]}
            )
            matched_filepath = ""
            for d in parent_recipe_dirs:
                # check if we are in the root of a parent repo, if not, ascend to the root
                # note that if the parents are not in a git repo, only the same
                # directory as the recipe will be searched for templates
                if not os.path.isdir(os.path.join(d, ".git")):
                    d = os.path.dirname(d)
                for path in Path(d).rglob(filename):
                    matched_filepath = str(path)
                    break
            if matched_filepath:
                self.output(f"File found at: {matched_filepath}")
                return matched_filepath

    def upload_script(
        self,
        jamf_url,
        script_name,
        script_path,
        category_id,
        script_category,
        script_info,
        script_notes,
        script_priority,
        script_parameter4,
        script_parameter5,
        script_parameter6,
        script_parameter7,
        script_parameter8,
        script_parameter9,
        script_parameter10,
        script_parameter11,
        script_os_requirements,
        token,
        obj_id=None,
    ):
        """Update script metadata."""

        # import script from file and replace any keys in the script
        if os.path.exists(script_path):
            with open(script_path, "r") as file:
                script_contents = file.read()
        else:
            raise ProcessorError("Script does not exist!")

        # substitute user-assignable keys
        script_contents = self.substitute_assignable_keys(script_contents)

        # priority has to be in upper case. Let's make it nice for the user
        if script_priority:
            script_priority = script_priority.upper()

        # build the object
        script_data = {
            "name": script_name,
            "info": script_info,
            "notes": script_notes,
            "priority": script_priority,
            "categoryId": category_id,
            "categoryName": script_category,
            "parameter4": script_parameter4,
            "parameter5": script_parameter5,
            "parameter6": script_parameter6,
            "parameter7": script_parameter7,
            "parameter8": script_parameter8,
            "parameter9": script_parameter9,
            "parameter10": script_parameter10,
            "parameter11": script_parameter11,
            "osRequirements": script_os_requirements,
            "scriptContents": script_contents,
        }

        self.output(
            "Script data:",
            verbose_level=2,
        )
        self.output(
            script_data,
            verbose_level=2,
        )

        script_json = self.write_json_file(script_data)

        self.output("Uploading script..")

        # if we find an object ID we put, if not, we post
        object_type = "script"
        if obj_id:
            url = "{}/{}/{}".format(jamf_url, self.api_endpoints(object_type), obj_id)
        else:
            url = "{}/{}".format(jamf_url, self.api_endpoints(object_type))

        count = 0
        while True:
            count += 1
            self.output(
                "Script upload attempt {}".format(count),
                verbose_level=2,
            )
            request = "PUT" if obj_id else "POST"
            r = self.curl(request=request, url=url, token=token, data=script_json)
            # check HTTP response
            if self.status_check(r, "Script", script_name) == "break":
                break
            if count > 5:
                self.output("Script upload did not succeed after 5 attempts")
                self.output("\nHTTP POST Response Code: {}".format(r.status_code))
                raise ProcessorError("ERROR: Script upload failed ")
            sleep(10)

        # clean up temp files
        self.clear_tmp_dir()

        return r

    def main(self):
        """Do the main thing here"""
        self.jamf_url = self.env.get("JSS_URL")
        self.jamf_user = self.env.get("API_USERNAME")
        self.jamf_password = self.env.get("API_PASSWORD")
        self.script_path = self.env.get("script_path")
        self.script_name = self.env.get("script_name")
        self.script_category = self.env.get("script_category")
        self.script_priority = self.env.get("script_priority")
        self.osrequirements = self.env.get("osrequirements")
        self.script_info = self.env.get("script_info")
        self.script_notes = self.env.get("script_notes")
        self.script_parameter4 = self.env.get("script_parameter4")
        self.script_parameter5 = self.env.get("script_parameter5")
        self.script_parameter6 = self.env.get("script_parameter6")
        self.script_parameter7 = self.env.get("script_parameter7")
        self.script_parameter8 = self.env.get("script_parameter8")
        self.script_parameter9 = self.env.get("script_parameter9")
        self.script_parameter10 = self.env.get("script_parameter10")
        self.script_parameter11 = self.env.get("script_parameter11")
        self.replace = self.env.get("replace_script")
        # handle setting replace in overrides
        if not self.replace or self.replace == "False":
            self.replace = False

        # clear any pre-existing summary result
        if "jamfscriptuploader_summary_result" in self.env:
            del self.env["jamfscriptuploader_summary_result"]
        script_uploaded = False

        # check for existing token
        self.output("Checking for existing authentication token", verbose_level=2)
        token = self.check_api_token()

        # if no valid token, get one
        if not token:
            enc_creds = self.get_enc_creds(self.jamf_user, self.jamf_password)
            self.output("Getting an authentication token", verbose_level=2)
            token = self.get_api_token(self.jamf_url, enc_creds)

        if not token:
            raise ProcessorError("No token found, cannot continue")

        # get the id for a category if supplied
        if self.script_category:
            self.output("Checking categories for {}".format(self.script_category))
            category_id = self.get_uapi_obj_id_from_name(
                self.jamf_url, "categories", self.script_category, token
            )
            if not category_id:
                self.output("WARNING: Category not found!")
                category_id = "-1"
            else:
                self.output(
                    "Category {} found: ID={}".format(self.script_category, category_id)
                )
        else:
            self.script_category = ""
            category_id = "-1"

        # handle files with no path
        if "/" not in self.script_path:
            found_template = self.get_path_to_file(self.script_path)
            if found_template:
                self.script_path = found_template
            else:
                raise ProcessorError(f"ERROR: Script file {self.script_path} not found")

        # now start the process of uploading the object
        if not self.script_name:
            self.script_name = os.path.basename(self.script_path)

        # check for existing script
        self.output(
            "Checking for existing '{}' on {}".format(self.script_name, self.jamf_url)
        )
        self.output(
            "Full path: {}".format(self.script_path),
            verbose_level=2,
        )
        obj_id = self.get_uapi_obj_id_from_name(
            self.jamf_url, "scripts", self.script_name, token
        )

        if obj_id:
            self.output(
                "Script '{}' already exists: ID {}".format(self.script_name, obj_id)
            )
            if self.replace:
                self.output(
                    "Replacing existing script as 'replace_script' is set to {}".format(
                        self.replace
                    ),
                    verbose_level=1,
                )
            else:
                self.output(
                    "Not replacing existing script. Use replace_script='True' to enforce.",
                    verbose_level=1,
                )
                return

        # post the script
        self.upload_script(
            self.jamf_url,
            self.script_name,
            self.script_path,
            category_id,
            self.script_category,
            self.script_info,
            self.script_notes,
            self.script_priority,
            self.script_parameter4,
            self.script_parameter5,
            self.script_parameter6,
            self.script_parameter7,
            self.script_parameter8,
            self.script_parameter9,
            self.script_parameter10,
            self.script_parameter11,
            self.osrequirements,
            token,
            obj_id,
        )
        script_uploaded = True

        # output the summary
        self.env["script_name"] = self.script_name
        self.env["script_uploaded"] = script_uploaded
        if script_uploaded:
            self.env["jamfscriptuploader_summary_result"] = {
                "summary_text": "The following scripts were created or updated in Jamf Pro:",
                "report_fields": [
                    "script",
                    "path",
                    "category",
                    "priority",
                    "os_req",
                    "info",
                    "notes",
                    "P4",
                    "P5",
                    "P6",
                    "P7",
                    "P8",
                    "P9",
                    "P10",
                    "P11",
                ],
                "data": {
                    "script": self.script_name,
                    "path": self.script_path,
                    "category": self.script_category,
                    "priority": str(self.script_priority),
                    "info": self.script_info,
                    "os_req": self.osrequirements,
                    "notes": self.script_notes,
                    "P4": self.script_parameter4,
                    "P5": self.script_parameter5,
                    "P6": self.script_parameter6,
                    "P7": self.script_parameter7,
                    "P8": self.script_parameter8,
                    "P9": self.script_parameter9,
                    "P10": self.script_parameter10,
                    "P11": self.script_parameter11,
                },
            }


if __name__ == "__main__":
    PROCESSOR = JamfScriptUploader()
    PROCESSOR.execute_shell()

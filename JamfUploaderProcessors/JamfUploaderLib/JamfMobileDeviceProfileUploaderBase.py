#!/usr/local/autopkg/python

"""
Copyright 2023 Graham Pugh

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import os.path
import sys
import plistlib
import subprocess
import uuid

from time import sleep

from autopkglib import (  # pylint: disable=import-error
    ProcessorError,
)

# to use a base module in AutoPkg we need to add this path to the sys.path.
# this violates flake8 E402 (PEP8 imports) but is unavoidable, so the following
# imports require noqa comments for E402
sys.path.insert(0, os.path.dirname(__file__))

from JamfUploaderBase import (  # pylint: disable=import-error, wrong-import-position
    JamfUploaderBase,
)


class JamfMobileDeviceProfileUploaderBase(JamfUploaderBase):
    """Class for functions used to upload a mobile device configuration profile to Jamf"""

    def get_existing_uuid_and_identifier(self, jamf_url, obj_id, token):
        """return the existing UUID to ensure we don't change it"""
        # first grab the payload from the xml object
        obj_type = "configuration_profile"
        existing_plist = self.get_api_obj_value_from_id(
            jamf_url,
            obj_type,
            obj_id,
            "general/payloads",
            token=token,
        )

        # Jamf seems to sometimes export an empty key which plistlib considers invalid,
        # so let's remove this
        existing_plist = existing_plist.replace("<key/>", "")

        # make the xml pretty so we can see where the problem importing it is better
        existing_plist = self.pretty_print_xml(bytes(existing_plist, "utf-8"))

        self.output(
            f"Existing payload (type: {type(existing_plist)}):", verbose_level=2
        )
        self.output(existing_plist.decode("UTF-8"), verbose_level=2)

        # now extract the UUID from the existing payload
        existing_payload = plistlib.loads(existing_plist)
        self.output("Imported payload", verbose_level=2)
        self.output(existing_payload, verbose_level=2)
        existing_uuid = existing_payload["PayloadUUID"]
        self.output(f"Existing PayloadUUID found: {existing_uuid}")
        existing_identifier = existing_payload["PayloadIdentifier"]
        self.output(f"Existing PayloadIdentifier found: {existing_uuid}")

        return existing_uuid, existing_identifier

    def replace_uuid_and_identifier_in_mobileconfig(
        self, mobileconfig_contents, existing_uuid, existing_identifier
    ):
        self.output("Updating the UUIDs in the mobileconfig", verbose_level=2)
        mobileconfig_contents["PayloadIdentifier"] = existing_identifier
        mobileconfig_contents["PayloadUUID"] = existing_uuid
        # with open(self.mobileconfig, "wb") as file:
        #     plistlib.dump(mobileconfig_contents, file)
        return mobileconfig_contents

    def unsign_signed_mobileconfig(self, mobileconfig_plist):
        """checks if profile is signed. This is necessary because Jamf cannot
        upload a signed profile, so we either need to unsign it, or bail"""
        output_path = os.path.join("/tmp", str(uuid.uuid4()))
        cmd = [
            "/usr/bin/security",
            "cms",
            "-D",
            "-i",
            mobileconfig_plist,
            "-o",
            output_path,
        ]
        self.output(cmd, verbose_level=1)

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, err = proc.communicate()
        if os.path.exists(output_path) and os.stat(output_path).st_size > 0:
            self.output(f"Profile is signed. Unsigned profile at {output_path}")
            return output_path
        elif err:
            self.output("Profile is not signed.")
            self.output(err, verbose_level=2)

    def upload_mobileconfig(
        self,
        jamf_url,
        mobileconfig_name,
        description,
        category,
        mobileconfig_plist,
        devicegroup_name,
        template_contents,
        profile_uuid,
        token,
        obj_id=0,
    ):
        """Update Configuration Profile metadata."""
        # remove newlines, tabs, leading spaces, and XML-escape the payload
        mobileconfig_plist = mobileconfig_plist.decode("UTF-8")
        mobileconfig_list = mobileconfig_plist.rsplit("\n")
        mobileconfig_list = [x.strip("\t") for x in mobileconfig_list]
        mobileconfig_list = [x.strip(" ") for x in mobileconfig_list]
        mobileconfig = "".join(mobileconfig_list)

        # substitute user-assignable keys
        replaceable_keys = {
            "mobileconfig_name": mobileconfig_name,
            "description": description,
            "category": category,
            "payload": mobileconfig,
            "devicegroup_name": devicegroup_name,
            "uuid": f"com.github.grahampugh.jamf-upload.{profile_uuid}",
        }

        # substitute user-assignable keys (escaping for XML)
        template_contents = self.substitute_limited_assignable_keys(
            template_contents, replaceable_keys, xml_escape=True
        )

        self.output(
            "Configuration Profile with intermediate substitution:", verbose_level=2
        )
        self.output(template_contents, verbose_level=2)

        # substitute user-assignable keys
        template_contents = self.substitute_assignable_keys(template_contents)

        self.output("Configuration Profile to be uploaded:", verbose_level=2)
        self.output(template_contents, verbose_level=2)

        self.output("Uploading Configuration Profile...")
        # write the template to temp file
        template_xml = self.write_temp_file(template_contents)

        # if we find an object ID we put, if not, we post
        object_type = "configuration_profile"
        url = "{}/{}/id/{}".format(jamf_url, self.api_endpoints(object_type), obj_id)

        count = 0
        while True:
            count += 1
            self.output(
                f"Configuration Profile upload attempt {count}", verbose_level=1
            )
            request = "PUT" if obj_id else "POST"
            r = self.curl(
                request=request,
                url=url,
                token=token,
                data=template_xml,
            )

            # check HTTP response
            if (
                self.status_check(
                    r, "Configuration Profile", mobileconfig_name, request
                )
                == "break"
            ):
                break
            if count > 5:
                self.output(
                    "ERROR: Configuration Profile upload did not succeed after 5 attempts"
                )
                self.output(f"\nHTTP POST Response Code: {r.status_code}")
                break
            if int(self.sleep) > 30:
                sleep(int(self.sleep))
            else:
                sleep(30)

        return r

    def execute(self):
        """Upload a mobile device configuration profile"""
        self.jamf_url = self.env.get("JSS_URL").rstrip("/")
        self.jamf_user = self.env.get("API_USERNAME")
        self.jamf_password = self.env.get("API_PASSWORD")
        self.client_id = self.env.get("CLIENT_ID")
        self.client_secret = self.env.get("CLIENT_SECRET")
        self.profile_name = self.env.get("profile_name")
        self.mobileconfig = self.env.get("mobileconfig")
        self.identifier = self.env.get("identifier")
        self.template = self.env.get("profile_template")
        self.profile_category = self.env.get("profile_category")
        self.organization = self.env.get("organization")
        self.profile_description = self.env.get("profile_description")
        self.profile_mobiledevicegroup = self.env.get("profile_mobiledevicegroup")
        self.replace = self.env.get("replace_profile")
        self.sleep = self.env.get("sleep")
        self.unsign = self.env.get("unsign_profile")
        # handle setting unsign in overrides
        if not self.unsign or self.unsign == "False":
            self.unsign = False
        # handle setting replace in overrides
        if not self.replace or self.replace == "False":
            self.replace = False

        # clear any pre-existing summary result
        if "JamfMobileDeviceProfileUploader_summary_result" in self.env:
            del self.env["JamfMobileDeviceProfileUploader_summary_result"]

        profile_updated = False

        # handle files with no path
        if self.mobileconfig and "/" not in self.mobileconfig:
            found_mobileconfig = self.get_path_to_file(self.mobileconfig)
            if found_mobileconfig:
                self.mobileconfig = found_mobileconfig
            else:
                raise ProcessorError(
                    f"ERROR: mobileconfig file {self.mobileconfig} not found"
                )
        if self.template and "/" not in self.template:
            found_template = self.get_path_to_file(self.template)
            if found_template:
                self.template = found_template
            else:
                raise ProcessorError(
                    f"ERROR: XML template file {self.template} not found"
                )

        # if an unsigned mobileconfig file is supplied we can get the name, organization and
        # description from it, but allowing the values to be substituted by Input keys
        if self.mobileconfig:
            self.output(f"mobileconfig file supplied: {self.mobileconfig}")
            # check if the file is signed
            mobileconfig_file = self.unsign_signed_mobileconfig(self.mobileconfig)
            # quit if we get an unsigned profile back and we didn't select --unsign
            if mobileconfig_file and not self.unsign:
                raise ProcessorError(
                    "Signed profiles cannot be uploaded to Jamf Pro via the API. "
                    "Use the GUI to upload the signed profile, or use --unsign to upload "
                    "the profile with the signature removed."
                )

            # import mobileconfig
            with open(self.mobileconfig, "rb") as file:
                mobileconfig_plist = file.read()
                # substitute user-assignable keys (requires decode to string)
                mobileconfig_plist = str.encode(
                    self.substitute_assignable_keys(
                        (mobileconfig_plist.decode()), xml_escape=True
                    )
                )
                mobileconfig_contents = plistlib.loads(mobileconfig_plist)
            try:
                mobileconfig_name = mobileconfig_contents["PayloadDisplayName"]
                self.output(f"Configuration Profile name: {mobileconfig_name}")
                self.output("Mobileconfig contents:", verbose_level=2)
                self.output(mobileconfig_plist.decode("UTF-8"), verbose_level=2)
            except KeyError:
                raise ProcessorError(
                    "ERROR: Invalid mobileconfig file supplied - cannot import"
                )
            try:
                description = mobileconfig_contents["PayloadDescription"]
            except KeyError:
                description = ""
            try:
                organization = mobileconfig_contents["PayloadOrganization"]
            except KeyError:
                organization = ""

        # automatically provide a description and organisation from the mobileconfig
        # if not provided in the options
        if not self.profile_description:
            if description:
                self.profile_description = description
            else:
                self.profile_description = (
                    "Config profile created by AutoPkg and "
                    "JamfMobileDeviceProfileUploader"
                )
        if not self.organization:
            if organization:
                self.organization = organization
            else:
                organization = "AutoPkg"
                self.organization = organization

        # import profile template
        with open(self.template, "r") as file:
            template_contents = file.read()

        # check for existing Configuration Profile
        self.output(f"Checking for existing '{mobileconfig_name}' on {self.jamf_url}")

        # get token using oauth or basic auth depending on the credentials given
        if self.jamf_url and self.client_id and self.client_secret:
            token = self.handle_oauth(self.jamf_url, self.client_id, self.client_secret)
        elif self.jamf_url and self.jamf_user and self.jamf_password:
            token = self.handle_api_auth(
                self.jamf_url, self.jamf_user, self.jamf_password
            )
        else:
            raise ProcessorError("ERROR: Credentials not supplied")

        obj_type = "configuration_profile"
        obj_name = mobileconfig_name
        obj_id = self.get_api_obj_id_from_name(
            self.jamf_url,
            obj_name,
            obj_type,
            token=token,
        )
        if obj_id:
            self.output(
                f"Configuration Profile '{mobileconfig_name}' already exists: ID {obj_id}"
            )
            if self.replace:
                # grab existing UUID from profile as it MUST match on the destination
                (
                    existing_uuid,
                    existing_identifier,
                ) = self.get_existing_uuid_and_identifier(self.jamf_url, obj_id, token)
                if self.mobileconfig:
                    # need to inject the existing payload identifier to prevent ghost profiles
                    mobileconfig_contents = (
                        self.replace_uuid_and_identifier_in_mobileconfig(
                            mobileconfig_contents, existing_uuid, existing_identifier
                        )
                    )
                    mobileconfig_plist = plistlib.dumps(mobileconfig_contents)
                else:
                    self.output("A mobileconfig was not supplied.")

                # now upload the mobileconfig by generating an XML template
                if mobileconfig_plist:
                    self.upload_mobileconfig(
                        self.jamf_url,
                        mobileconfig_name,
                        self.profile_description,
                        self.profile_category,
                        mobileconfig_plist,
                        self.profile_mobiledevicegroup,
                        template_contents,
                        existing_uuid,
                        token,
                        obj_id=obj_id,
                    )
                    profile_updated = True
            else:
                self.output(
                    "Not replacing existing Configuration Profile. "
                    "Override the replace_profile key to True to enforce."
                )
        else:
            self.output(
                f"Configuration Profile '{mobileconfig_name}' not found - will create"
            )
            new_uuid = str(uuid.uuid4())

            # now upload the mobileconfig by generating an XML template
            if mobileconfig_plist:
                self.upload_mobileconfig(
                    self.jamf_url,
                    mobileconfig_name,
                    self.profile_description,
                    self.profile_category,
                    mobileconfig_plist,
                    self.profile_mobiledevicegroup,
                    template_contents,
                    new_uuid,
                    token=token,
                )
                profile_updated = True
            else:
                raise ProcessorError(
                    "A mobileconfig was not generated so cannot upload."
                )

        # output the summary
        self.env["profile_name"] = self.profile_name
        self.env["profile_updated"] = profile_updated
        if profile_updated:
            self.env["JamfMobileDeviceProfileUploader_summary_result"] = {
                "summary_text": (
                    "The following configuration profiles were uploaded to "
                    "or updated in Jamf Pro:"
                ),
                "report_fields": ["mobileconfig_name", "profile_category"],
                "data": {
                    "mobileconfig_name": mobileconfig_name,
                    "profile_category": self.profile_category,
                },
            }

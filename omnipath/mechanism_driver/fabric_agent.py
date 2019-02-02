# Copyright (c) 2019 Intel Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import paramiko

from oslo_config import cfg as config
from oslo_log import log as logging

from omnipath.common import omnipath_conf
from omnipath.common import omnipath_exceptions

LOG = logging.getLogger(__name__)
OPA_BINARY = "opafmvf"


class FabricAgentCLI(object):
    def __init__(self):
        self._agent_hostname = None
        self._agent_username = None
        self._agent_key_path = None
        config.CONF.register_opts(omnipath_conf.omnipath_opts,
                                  "ml2_omnipath")

        self._read_config()

        self.client = paramiko.SSHClient()

    def _read_config(self):
        self._agent_hostname = config.CONF.ml2_omnipath.ip_address
        LOG.info("Fabric Agent IP address: %s", self._agent_hostname)
        self._agent_username = config.CONF.ml2_omnipath.username
        self._agent_key_path = config.CONF.ml2_omnipath.ssh_key

    def connect(self):
        try:
            key = paramiko.RSAKey.from_private_key_file(self._agent_key_path)
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                self._agent_hostname, port=22,
                username=self._agent_username, pkey=key)
        except omnipath_exceptions.FabricAgentCLIError:
            LOG.error("Error connecting to Omnipath FM")

    def execute_command(self, command):
        self.connect()
        exec_engine = self.client.get_transport().open_session()
        exec_engine.exec_command(command)
        LOG.debug("Command dispatched %s", command)
        exec_status = exec_engine.recv_exit_status()
        self.client.close()
        return exec_status

    def _prepare_command(self, cmd):
        command = ""
        for bit in cmd:
            command = command + " " + bit
        return command

    def osfa_config_commands(self, command, vf_name, *args):
        try:
            if command == "create":
                pkey = "--pkey " + str(args[0])
                cmd = [OPA_BINARY, "create", vf_name, pkey]
            elif command == "delete":
                cmd = [OPA_BINARY, "delete", vf_name]
            elif command == "add":
                cmd = [OPA_BINARY, "add", vf_name,
                       "".join(str(x + " ") for x in args).rstrip()]
            elif command == "remove":
                cmd = [OPA_BINARY, "remove", vf_name,
                       "".join(str(x + " ") for x in args).rstrip()]
            else:
                raise omnipath_exceptions.FabricAgentUnknownCommandError
            final_cmd = self._prepare_command(cmd)
            return self.execute_command(final_cmd)
        except omnipath_exceptions.FabricAgentUnknownCommandError:
            LOG.error(command + " not supported in opafmvf CLI")

    def osfa_query_commands(self, command, vf_name, *args):
        try:
            if command == "exist":
                cmd = [OPA_BINARY, "exist", vf_name]
            elif command == "ismember":
                cmd = [OPA_BINARY, "ismember", vf_name,
                       "".join(str(x + " ") for x in args).rstrip()]
            elif command == "isnotmember":
                cmd = [OPA_BINARY, "isnotmember", vf_name,
                       "".join(str(x + " ") for x in args).rstrip()]
            else:
                raise omnipath_exceptions.FabricAgentUnknownCommandError
            final_cmd = self._prepare_command(cmd)
            return self.execute_command(final_cmd)
        except omnipath_exceptions.FabricAgentUnknownCommandError:
            LOG.error(command + " not supported in opafmvf CLI")

    def osfa_management_commands(self, command):
        try:
            if command == "reset":
                cmd = [OPA_BINARY, "reset"]
            elif command == "commit":
                cmd = [OPA_BINARY, "commit", "-f"]
            elif command == "reload":
                cmd = [OPA_BINARY, "reload"]
            elif command == "restart":
                cmd = [OPA_BINARY, "restart"]
            elif command == "abort":
                cmd = [OPA_BINARY, "killall -9", OPA_BINARY]
            else:
                raise omnipath_exceptions.FabricAgentUnknownCommandError
            final_cmd = self._prepare_command(cmd)
            return self.execute_command(final_cmd)
        except omnipath_exceptions.FabricAgentUnknownCommandError:
            LOG.error(command + " not supported in opafmvf CLI")


class FabricAgentClient(object):
    def __init__(self):
        self.cli = FabricAgentCLI()

    # Neutron FabricAgentClient sending requests to Fabric Agent:
    def full_sync(self, guids_info):
        """Will send list of GUIDs to be created/deleted to
        OpenStack Fabric Agent. The creates/deletes are implicit.

        :param guid_info: {vf_name1: [guid1, guid2], vf_name2: [guid3, guid4]}
        :return: bind status
        """

        # lock
        # Add global lock so that this command is sent by
        # only one neutron server
        for vf_name, guids in guids_info:
            config_status = self.cli.osfa_config_commands(
                "add", vf_name, guids)
            if config_status == 2:
                return "ERROR"

        commit_status = self.cli.osfa_management_commands("commit")
        if commit_status != 0:
            return "ERROR"

        reload_status = self.cli.osfa_management_commands("reload")
        if reload_status != 0:
            # Port Status ERROR
            return "ERROR"

        # Port status down
        return "DOWN"

    def get_port_status(self, vf_name, guid):
        """

        :param vf_name: Name of the VF
        :param guid: ID of the physical server
        :return: bind status
        """

        query_status = self.cli.osfa_query_commands(
            "ismember", vf_name, [guid])
        if query_status == 0:
            return "UP"
        else:
            return "DOWN"

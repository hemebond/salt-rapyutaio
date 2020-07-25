import os
import logging
from urllib.parse import urlencode
from enum import Enum
from copy import deepcopy

import salt.utils.http
import salt.utils.json
from salt.exceptions import CommandExecutionError, MinionError, SaltInvocationError




log = logging.getLogger(__name__)



class phase(Enum):
	def __str__(self):
		return str(self.value)

	INPROGRESS = 'In progress'
	PROVISIONING = 'Provisioning'
	SUCCEEDED = 'Succeeded'
	FAILED_TO_START = 'Failed to start'
	PARTIALLY_DEPROVISIONED = 'Partially deprovisioned'
	STOPPED = 'Deployment stopped'

class status(Enum):
	def __str__(self):
		return str(self.value)

	RUNNING = 'Running'
	PENDING = 'Pending'
	ERROR = 'Error'
	UNKNOWN = 'Unknown'
	STOPPED = 'Stopped'


__virtual_name__ = "rapyutaio"
def __virtual__():
	return __virtual_name__



def _error(ret, err_msg):
    ret['result'] = False
    ret['comment'] = err_msg
    return ret



def _get_config(project_id, auth_token):
	"""
	"""

	if not project_id and __salt__["config.option"]("rapyutaio.project_id"):
		project_id = __salt__["config.option"]("rapyutaio.project_id")

	if not auth_token and __salt__["config.option"]("rapyutaio.auth_token"):
		auth_token = __salt__["config.option"]("rapyutaio.auth_token")

	return (project_id, auth_token)



def get_packages(name=None,
                 phase=[],
                 project_id=None,
                 auth_token=None):
	"""
	List of package summaries in the project

	project_id

		string

	Authorization

		string

	phase

		array[string]

	name

		string

	version

		string

	salt-call --log-level=debug --local rapyutaio.get_packages phase=["In progress","Succeeded"]
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}
	params = {
		'phase': phase,
	}
	url = "https://gacatalog.apps.rapyuta.io/v2/catalog?%s" % urlencode(params, doseq=True)

	response =  __utils__['http.query'](url=url,
	                                    header_dict=header_dict,
	                                    method="GET")

	if 'error' in response:
		if response['status'] != 404:
			raise CommandExecutionError(response['error'])
		else:
			return []

	# The response "body" will be string of JSON
	try:
		response_body = __utils__['json.loads'](response['body'])
	except JSONDecodeError as e:
		raise CommandExecutionError(e)

	# The packages are listed under the "services" key
	try:
		packages = response_body['services']
	except KeyError as e:
		log.debug(response_body)
		raise CommandExecutionError(e)

	if name is not None:
		packages = [
			pkg for pkg in packages if pkg['name'] == name
		]

	log.debug(packages)

	return packages



def get_package(package_uid=None,
                name=None,
                version=None,
                project_id=None,
                auth_token=None):
	"""
	Return a dict of information about a single package

	project_id

		string

	Authorization

		string

	package_uid

		string

	name

		string

	version

		string

	Returns:
		False: file not found
		Exception: something went wrong
		Dict: package
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	if package_uid is None:
		if name is not None and version is not None:
			#
			# Fetch a single package via its name and version
			#
			packages = get_packages(name=name,
			                        project_id=project_id,
			                        auth_token=auth_token)

			# Don't try to process an error response
			if 'error' in packages:
				return packages

			# Need to accept version with and without the 'v' prefix
			if version[0] != 'v':
				version = 'v' + version

			# Return the first package that matches the version
			for pkg_summary in packages:
				if pkg_summary['metadata']['packageVersion'] == version:
					package_uid = pkg_summary['id']
		else:
			raise SaltInvocationError(
				"Require either 'package_uid', or 'name' and 'version'"
			)

	if package_uid is not None:
		#
		# Fetch a single package via its UID
		#
		url = "https://gacatalog.apps.rapyuta.io/serviceclass/status"
		header_dict = {
			"accept": "application/json",
			"project": project_id,
			"Authorization": "Bearer " + auth_token,
		}
		data = {
			"package_uid": package_uid,
		}
		response =  __utils__['http.query'](url=url,
		                                    header_dict=header_dict,
		                                    method="GET",
		                                    params=data,
		                                    status=True)

		if 'error' in response:
			if response['status'] != 404:
				raise CommandExecutionError(response['error'])
			else:
				return False

		return __utils__['json.loads'](response['body'])

	return False



def delete_package(package_uid=None,
                   name=None,
                   version=None,
                   project_id=None,
                   auth_token=None,
                   ):
	"""
	Delete a package

	Return:
		True: file deleted
		False: file not there
		Exception: could not delete
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	if package_uid is None:
		if name is not None and version is not None:
			#
			# Fetch the package UID using its name and version
			#
			package = get_package(name=name,
			                      version=version,
			                      project_id=project_id,
			                      auth_token=auth_token)

			if 'error' in package:
				return package

			package_uid = package['packageInfo']['guid']
		else:
			raise SaltInvocationError(
				"Require either 'package_uid', or 'name' and 'version'"
			)

	#
	# Send the delete request
	#
	url = "https://gacatalog.apps.rapyuta.io/serviceclass/delete"
	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}
	data = {
		"package_uid": package_uid,
	}
	response =  __utils__['http.query'](url=url,
	                                    header_dict=header_dict,
	                                    method="DELETE",
	                                    params=data,
	                                    status=True)
	log.debug(response)

	if response['status'] == 200:
		return True

	if 'error' in response:
		if response['status'] != 404:
			raise CommandExecutionError(response['error'])

	return False



def create_package(source=None,
                   content=None,
                   project_id=None,
                   auth_token=None,
                   dry_run=False):
	"""
	Upload a package manifest
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	url = "https://gacatalog.apps.rapyuta.io/serviceclass/add"
	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}

	if content is None:
		if source is None:
			raise SaltInvocationError(
				"create_or_update_package requires either source or content"
			)

		file_name = __salt__["cp.cache_file"](source)

		if file_name is not False:
			with salt.utils.files.fopen(file_name, "r") as _f:
				file_name_part, file_extension = os.path.splitext(file_name)

				if file_extension == '.json':
					content = __utils__['json.load'](_f)
				elif file_extension in ['.yaml', '.yml']:
					content = __utils__['yaml.load'](_f)
				else:
					raise SaltInvocationError(
						"Source file must be a JSON (.json) or YAML (.yaml, .yml) file"
					)
		else:
			raise CommandExecutionError(
				"File '{}' does not exist".format(file_name)
			)

	response = __utils__['http.query'](url=url,
	                                   header_dict=header_dict,
	                                   method="POST",
	                                   data=__utils__['json.dumps'](content),
	                                   status=True)
	log.debug(response)

	if 'error' in response:
		raise CommandExecutionError(
			response['error']
		)

	return __utils__['json.loads'](response['body'])



def list_networks(project_id=None,
                  auth_token=None):
	"""
	List all routed networks
	"""

	(project_id, auth_token) = _get_config(project_id, auth_token)

	url = "https://gacatalog.apps.rapyuta.io/routednetwork"
	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}

	return salt.utils.http.query(url=url,
	                             header_dict=header_dict,
	                             method="GET")



def get_network(network_guid,
                project_id=None,
                auth_token=None):
	"""
	Get a Routed Network
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	url = "https://gacatalog.apps.rapyuta.io/routednetwork/%s" % network_guid
	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}

	return salt.utils.http.query(url=url,
	                             header_dict=header_dict,
	                             method="GET")





def add_network(project_id=None,
                auth_token=None):
	"""
	Create a new Routed Network
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	url = "https://gacatalog.apps.rapyuta.io/routednetwork"
	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}


	ret = salt.utils.http.query(url=url,
	                            header_dict=header_dict,
	                            method="POST",
	                            data=salt.utils.json.dumps(contents))

	if ret['status'] == 409:
		# Conflict: netowkr already exists with this name
		pass

	return ret



def delete_network(network_guid,
                   project_id=None,
                   auth_token=None):
	"""
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	url = "https://gacatalog.apps.rapyuta.io/routednetwork/%s" % network_guid
	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}

	return salt.utils.http.query(url=url,
	                             header_dict=header_dict,
	                             method="DELETE")



def list_deployments(project_id=None,
                     auth_token=None,
                     package_uid='',
                     phase=[]):
	"""
	salt-call --log-level=debug --local rapyutaio.list_deployments phase=["In progress","Succeeded"]
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	url = "https://gacatalog.apps.rapyuta.io/deployment/list"
	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}
	params = {
		'package_uid': package_uid,
		'phase': phase,
	}
	url = "https://gacatalog.apps.rapyuta.io/deployment/list?%s" % urlencode(params, doseq=True)

	return salt.utils.http.query(url=url,
	                             header_dict=header_dict,
	                             method="GET")


def get_deployment(deploymentid,
                   project_id=None,
                   auth_token=None):
	"""
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}
	url = "https://gacatalog.apps.rapyuta.io/serviceinstance/%s" % deploymentid

	return salt.utils.http.query(url=url,
	                             header_dict=header_dict,
	                             method="GET")



def get_dependencies(deploymentid,
                     project_id=None,
                     auth_token=None):
	"""
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}
	url = "https://gacatalog.apps.rapyuta.io/serviceinstance/%s/dependencies" % deploymentid

	return salt.utils.http.query(url=url,
	                             header_dict=header_dict,
	                             method="GET")


def deprovision(deploymentid,
                package_uid,
                plan_id,
                project_id=None,
                auth_token=None):
	"""
	Response:

		{"async":false,"component_status":null}
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	header_dict = {
		"accept": "application/json",
		"project": project_id,
		"Authorization": "Bearer " + auth_token,
	}
	params = {
		"service_id": package_uid,
		"plan_id": plan_id,
	}
	url = "https://gacatalog.apps.rapyuta.io/v2/service_instances/%s" % deploymentid

	return salt.utils.http.query(url=url,
	                             header_dict=header_dict,
	                             method="DELETE",
	                             params=params)



def get_manifest(package_uid,
                 project_id=None,
                 auth_token=None):
	"""
	Get a manifest for a package like you would through the web interface
	"""
	(project_id, auth_token) = _get_config(project_id, auth_token)

	package = get_package(package_uid=package_uid,
	                      project_id=project_id,
	                      auth_token=auth_token)

	if not package:
		return False

	header_dict = {
		"accept": "application/json"
	}
	url = package['packageUrl']

	response = __utils__['http.query'](url=url,
	                                   header_dict=header_dict,
	                                   method="GET")

	if 'error' in response:
		raise CommandExecutionError(
			response['error']
		)

	return __utils__['json.loads'](response['body'])
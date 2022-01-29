import sys
import os
import argparse
import re
import boto3
import json
import time
import datetime
import zipfile
import glob
from botocore.config import Config
from botocore.exceptions import ClientError


class libEl:
  def __init__(self, module, params):

    self.module = module
    self.params = params
    self.prefix = params[self.module+"_prefix"]
    self.stage = params[self.module+"_stage"]

    if params['deploy_type'] == "profile":
      self.session = boto3.Session(profile_name=self.module)
    elif params['deploy_type'] == "credentials":
      self.session = boto3.Session(
        aws_access_key_id=params[self.module+'_access_key'],
        aws_secret_access_key=params[self.module+'_access_key']
      )
    else:
      sys.exit("This script you can use only with deployment by profile or credentials")

    self.resources = {}
    self.resources["s3"] = self.session.resource('s3')
    self.resources["cfn"] = self.session.resource('cloudformation')
    self.resources["cfn_client"] = self.session.client('cloudformation')
    self.resources["sts"] = self.session.client('sts')
    self.resources["ssm"] = self.session.client('ssm')

    self.test = params["test"]

    pass

  def flatten_list_of_lists(self, result):
    return [item for sublist in result for item in sublist]

  def flatten_by_key(self, result, key):
    filtered_result = list(filter(lambda x: key in x, result))
    non_flat = list(map(lambda x: x[key], filtered_result))
    return self.flatten_list_of_lists(non_flat)

  def getAccoundId(self):
      return self.resources["sts"].get_caller_identity().get('Account')

  ## CLOUDFORMATION
  def get_all_stacks(self):
    return [stack.name for stack in self.resources["cfn"].stacks.all()]

  def get_stackname(self, template_name):
    return template_name
    # return self.prefix + '-' + template_name + '-' + self.stage

  def get_stack(self, stack_name):
    try:
      stack = self.resources["cfn_client"].describe_stacks(
                  StackName=stack_name
              )
    except ClientError as ex:
      error_message = ex.response['Error']['Message']
      print(error_message)
      return None
    else:
      return stack["Stacks"][0]

  def get_stack_resources(self, stack_name):
    try:
      stack = self.resources["cfn_client"].describe_stack_resources(
                  StackName=stack_name
              )
    except ClientError as ex:
      error_message = ex.response['Error']['Message']
      print("I can't read resources - miss step")
      print(error_message)
      return None
    else:
      if stack["StackResources"]:
        return stack["StackResources"]
      else:
        return None

  def get_status_of_stacks(self):
    paginator = self.resources["cfn_client"].get_paginator('describe_stacks')
    page_iterator = paginator.paginate()
    result = list(page_iterator)
    flat_list = self.flatten_by_key(result, 'Stacks')
    return list(map(lambda x: ({'name': x['StackName'], 'status': x['StackStatus'], 'id': x['StackId']}), flat_list))

  def get_template_string(self, template_name):
    try:
      with open(template_name, 'r') as template_file:
        return template_file.read()
    except OSError as ex:
      print(ex)
    else:
      print("Przeczytalem")

  def get_parameters_file(self, template_name):
    with open(template_name, 'r') as parameter_fileobj:
      parameter_data = json.load(parameter_fileobj)
      parameters = parameter_data['Parameters']
      parameters_cf = list(map(lambda x: {'ParameterKey': x , 'ParameterValue': parameters[x]}, parameters.keys()))
      return parameters_cf

  def get_parameters_array(self, parameters_array):
      parameters = parameters_array
      parameters_cf = list(map(lambda x: {'ParameterKey': x , 'ParameterValue': parameters[x]}, parameters.keys()))
      return parameters_cf

  def does_stack_exist(self, stack_name):
    stacks = self.get_status_of_stacks()
    stack_names = list(map(lambda x: x['name'], stacks))
    if stack_name in stack_names:
      return list(filter(lambda x: x['name'] == stack_name, stacks))[0]
    else:
      return None

  def deploy_template(self, template_name, template_file, parameters_file="None", parameters_array="None", deploy_type="changeset"):
    stack_name = self.get_stackname(template_name)
    stack = self.does_stack_exist(stack_name)
    if stack is None and (deploy_type == "always" or deploy_type == "create"):
      print(self.module+': stack ' + stack_name + ' does not exist - I will try create')
      if self.test == "false":
        self.create(template_name, template_file, parameters_file, parameters_array)
    elif deploy_type == "changeset":
      print(self.module+': stack ' + stack_name + ' exists - I will try create changeset')
      if self.test == "false":
        self.create_changeset(template_name, template_file, parameters_file, parameters_array)
    elif deploy_type == "always" or deploy_type == "update":
      print(self.module+': stack ' + stack_name + ' exists - I will update')
      if self.test == "false":
        self.update(template_name, template_file, parameters_file, parameters_array)
    else:
      print('stack ' + stack_name + ' exists - nothing to do - update was blocked')
  
  def create(self, template_name, template_file, parameters_file, parameters_array):
    try:
      stack_name = self.get_stackname(template_name)
      
      if parameters_file != "None":
        parameters = self.get_parameters_file(parameters_file)
      elif parameters_array != "None":
        parameters = self.get_parameters_array(parameters_array)
      elif parameters_array == "None" and parameters_file == "None":
        parameters = []
        
      stack_result = self.resources["cfn_client"].create_stack(
          StackName=stack_name,
          TemplateBody=self.get_template_string(template_file),
          Capabilities=['CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
          OnFailure='ROLLBACK',
          EnableTerminationProtection=False,
          Parameters=parameters
      )
      waiter = self.resources["cfn_client"].get_waiter('stack_create_complete')
      print("...waiting for stack to be ready...")
      waiter.wait(StackName=stack_name,
                  WaiterConfig={
                      'Delay': 15,
                      'MaxAttempts': 100
                  })
    except ClientError as ex:
      print("ERROR ------- ZOBACZ")
      print(ex)
      error_message = ex.response['Error']['Message']
      if error_message == 'No updates are to be performed.':
        print("No changes")
      else:
        print(error_message)
        raise
    else:
      out=self.resources["cfn_client"].describe_stacks(StackName=stack_result['StackId'])
      print(out["Stacks"][0]["StackStatus"])

  def update(self, template_name, template_file, parameters_file, parameters_array):
    try:
      stack_name = self.get_stackname(template_name)
      
      if parameters_file != "None":
        parameters = self.get_parameters_file(parameters_file)
      elif parameters_array != "None":
        parameters = self.get_parameters_array(parameters_array)
      elif parameters_array == "None" and parameters_file == "None":
        parameters = []

      stack_result = self.resources["cfn_client"].update_stack(
        StackName=stack_name,
        TemplateBody=self.get_template_string(template_file),
        Capabilities=['CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
        Parameters=parameters
      )
      waiter = self.resources["cfn_client"].get_waiter('stack_update_complete')
      print("...waiting for stack to be ready...")
      waiter.wait(StackName=stack_name,
        WaiterConfig={
            'Delay': 15,
            'MaxAttempts': 100
        })
    except ClientError as ex:
      error_message = ex.response['Error']['Message']
      if error_message == 'No updates are to be performed.':
          print("No changes")
      else:
          print(error_message)
          raise
    else:
      out=self.resources["cfn_client"].describe_stacks(StackName=stack_result['StackId'])
      print(out["Stacks"][0]["StackStatus"])

  def create_changeset(self, template_name, template_file, parameters_file, parameters_array):
    try:
      stack_name = self.get_stackname(template_name)
      changeSetName = stack_name+"-"+datetime.datetime.strftime(datetime.datetime.now(), '%Y%m%d-%H%M%S')
      
      if parameters_file != "None":
        parameters = self.get_parameters_file(parameters_file)
      elif parameters_array != "None":
        parameters = self.get_parameters_array(parameters_array)
      elif parameters_array == "None" and parameters_file == "None":
        parameters = []
        
      stack_result = self.resources["cfn_client"].create_change_set(
          StackName=stack_name,
          TemplateBody=self.get_template_string(template_file),
          Capabilities=['CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
          ChangeSetType="UPDATE",
          ChangeSetName=changeSetName,
          Parameters=parameters
      )
      waiter = self.resources["cfn_client"].get_waiter('change_set_create_complete')
      print("...waiting for change set to be ready...")
      waiter.wait(ChangeSetName=stack_result['Id'],
                  WaiterConfig={
                      'Delay': 15,
                      'MaxAttempts': 100
                  })
    except ClientError as ex:
      print(ex)
      raise
    else:
      input("When you accept change set, please press Enter to continue...")
  
  def delete_stack(self, template_name, roleARN=None):
    stack_name = self.get_stackname(template_name)
    print("* Stack will be delete: "+stack_name)

    stack = self.get_stack(stack_name)
    if stack != None:
      
      stack_resources = self.get_stack_resources(stack_name)
      if stack_resources != None:
        for stack_resource in stack_resources:
          # print(stack_resource)
          if stack_resource["ResourceType"] == "AWS::S3::Bucket":
            print("** I founded bucket s3: "+ stack_resource["PhysicalResourceId"])
            self.clean_bucket(stack_resource["PhysicalResourceId"])

      if self.test == "false":
        try:
          print("** Try delete: "+stack_name)

          if roleARN == None:
            self.resources["cfn_client"].delete_stack(
                StackName=stack_name
            )
          else:
            self.resources["cfn_client"].delete_stack(
                StackName=stack_name,
                RoleARN=roleARN
            )

          waiter = self.resources["cfn_client"].get_waiter('stack_delete_complete')
          print("...waiting for stack to be ready...")
          waiter.wait(StackName=stack_name,
                      WaiterConfig={
                          'Delay': 15,
                          'MaxAttempts': 100
                      })
        except ClientError as ex:
          print (ex.response['Error']['Message'])
          raise
        else:
          print("Stack was delete")
      else:
        print("** testing mode")
    else:
      print("! Stack not exist: "+stack_name)

  ##SSM
  def put_ssm_parameter(self, parameter_name, parameter_value):
    return self.resources["ssm"].put_parameter(
        Name=parameter_name,
        Type='String',
        Value=parameter_value,
        Overwrite=True
    )

  def get_ssm_parameter(self, parameter_name):
    return self.resources["ssm"].get_parameter(
        Name=parameter_name,
        WithDecryption=False
    )['Parameter']['Value']
    
  ## S3 and create archive
  def clean_bucket(self, bucket_name):
    print("* Clean bucket s3: "+bucket_name)
    if self.test == "false":
      try:
        files = self.resources["s3"].Bucket(bucket_name)
        files.object_versions.delete()
      except ClientError as e:
          print(e)

  def delete_bucket(self, bucket_name):
    print("* DELETE bucket s3: "+bucket_name)
    if self.test == "false":
      try:
        bucket = self.resources["s3"].Bucket(bucket_name)
        bucket.delete()
      except ClientError as e:
          print(e)

  def copy_file_to_s3(self, file, s3_bucket, s3_object_path_with_file_name):
    print("File: "+file+" -> s3://"+s3_bucket+"/"+s3_object_path_with_file_name)
    if self.test == "false":
      try:
        self.resources["s3"].meta.client.upload_file(file, s3_bucket, s3_object_path_with_file_name)
      except ClientError as ex:
        print (ex.response['Error']['Message'])
        raise

  def copy_dir_to_s3(self, dir, s3_bucket, s3_object_path_with_file_name):
    print("Copy all file from dir: "+dir)
    for file in glob.glob(os.path.join(dir, '*')):
      filename=os.path.basename(file)
      print("File: "+file+" -> s3://"+s3_bucket+"/"+s3_object_path_with_file_name+filename)
      if self.test == "false":
        try:
          self.resources["s3"].meta.client.upload_file(file, s3_bucket, s3_object_path_with_file_name+filename)
        except ClientError as ex:
          print (ex.response['Error']['Message'])
          raise

  def zip_folder(self, target_zip_file, directory_to_be_zipped):
    zipobj = zipfile.ZipFile(target_zip_file, 'w', zipfile.ZIP_DEFLATED)
    rootlen = len(directory_to_be_zipped)
    for base, dirs, files in os.walk(directory_to_be_zipped):
        if '.git' in dirs:
          dirs.remove('.git')
        if 'tests_web' in dirs:
          dirs.remove('tests_web')
        if 'migration' in dirs:
          dirs.remove('migration')
        for file in files:
            fn = os.path.join(base, file)
            zipobj.write(fn, fn[rootlen:])

  def create_deployment_package(self, package, dir_to_archive):
    source_code_package_name = package

    print("Archive this location: "+dir_to_archive+" -> "+source_code_package_name)

    self.zip_folder(source_code_package_name, dir_to_archive)

  def get_all_buckets(self):
    return [bucket.name for bucket in self.resources["s3"].buckets.all()]


  # def tested(self):
    # print(out["Stacks"][0]["StackStatus"])
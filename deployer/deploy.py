import sys
import argparse
import re
import boto3
import glob
import os
import time
from libEl import libEl 

#Login as cicd
#Login as app
#python3 deployer/deploy.py --app_stage sbx [--dry true|false]

parser = argparse.ArgumentParser()
DIR_APP = os.path.dirname(os.path.realpath(__file__)).rsplit('/', 1)[0]+"/"
DEFAULT_NAME_PROJECT = "aws-deployer"

def init():
  global PARAMS, AWS_CICD, AWS_APP
  parser.add_argument('--deploy_type', help='type of deploy: profile or credentials', type=str, default="profile", choices=['profile', 'credentials'])

  parser.add_argument('--cicd_prefix', help='cicd account prefix', type=str, default=DEFAULT_NAME_PROJECT)
  parser.add_argument('--cicd_stage', help='cicd account stage', type=str, default="all")
  parser.add_argument('--cicd_access_key', help='cicd access key', type=str, default="none")
  parser.add_argument('--cicd_secret_key', help='cicd secret key', type=str, default="none")

  parser.add_argument('--app_prefix', help='app account prefix', type=str, default=DEFAULT_NAME_PROJECT)
  parser.add_argument('--app_stage', help='app account stage', type=str, required=True)
  parser.add_argument('--app_access_key', help='app access key', type=str, default="none")
  parser.add_argument('--app_secret_key', help='app secret key', type=str, default="none")

  parser.add_argument('--dry', '-d', help='Run only testing', type=str, default="true", choices=['true', 'false'])
  args = parser.parse_args()

  PARAMS = {}
  PARAMS["deploy_type"] = args.deploy_type

  PARAMS["cicd_prefix"] = args.cicd_prefix
  PARAMS["cicd_stage"] = args.cicd_stage
  PARAMS["cicd_access_key"] = args.cicd_access_key
  PARAMS["cicd_secret_key"] = args.cicd_secret_key

  PARAMS["app_prefix"] = args.app_prefix
  PARAMS["app_stage"] = args.app_stage
  PARAMS["app_access_key"] = args.app_access_key
  PARAMS["app_secret_key"] = args.app_secret_key

  PARAMS["test"] = args.dry

  AWS_CICD = libEl('cicd', PARAMS)
  AWS_APP = libEl('app', PARAMS)

  print("You are using CICD Account: "+AWS_CICD.getAccoundId()+" and APP Account: "+AWS_APP.getAccoundId())
  print("Project name: "+DEFAULT_NAME_PROJECT)
  print("Dir app: "+DIR_APP)

  ##################
  ## STEPS TO DEPLOY
  ##################
  # first_deploy()
  # update_cicd()
  send_zips()

  ## END

##################
## STEP FUNCTIONS
##################
def first_deploy():
  AWS_CICD.deploy_template(
      template_name=AWS_CICD.prefix+"-global-names", 
      template_file=DIR_APP+'code/cicd/names.template',
      parameters_array={"projectName":AWS_CICD.prefix},
      deploy_type="create"
  )

  AWS_APP.deploy_template(
      template_name=AWS_APP.prefix+"-global-names", 
      template_file=DIR_APP+'code/cicd/names.template',
      parameters_array={"projectName":AWS_APP.prefix},
      deploy_type="create"
  )

  AWS_CICD.deploy_template(
      template_name=AWS_CICD.prefix+"-global-cicd",
      template_file=DIR_APP+'code/cicd/cicd.template',
      parameters_array={
        "stage":AWS_CICD.stage,
        "sbxInfrastructureKeyId":"none",
        "devInfrastructureKeyId":"none",
        "qaInfrastructureKeyId":"/qa/infrastructureKeyId",
        "prdInfrastructureKeyId":"/prd/infrastructureKeyId",
        "crossAccountRequiments":"no"
        },
      deploy_type="create"
  )
  
  AWS_APP.deploy_template(
      template_name=AWS_APP.prefix+"-global-cicd", 
      template_file=DIR_APP+'code/cicd/cicd.template',
      parameters_array={
        "stage":AWS_APP.stage,
        "projectName":f"/{AWS_APP.prefix}/projectName",
        "deploymentBucketName":f"/{AWS_APP.prefix}/deploymentBucketName",
        "artifactBucketName":f"/{AWS_APP.prefix}/artifactBucketName",
        "codePipelineSourceBucketName":f"/{AWS_APP.prefix}/codePipelineSourceBucketName",
        "sbxInfrastructureKeyId": "/sbx/infrastructureKeyId" if AWS_APP.stage == "sbx" else "none",
        "devInfrastructureKeyId": "/dev/infrastructureKeyId" if AWS_APP.stage == "dev" else "none",
        "qaInfrastructureKeyId": "/qa/infrastructureKeyId" if AWS_APP.stage == "qa" else "none",
        "prdInfrastructureKeyId": "/prd/infrastructureKeyId" if AWS_APP.stage == "prd" else "none",
        "crossAccountRequiments":"yes"
        },
      deploy_type="create"
  )


def update_cicd():
  print("###################################")
  print("From now template: code/cicd/cicd.template")
  print("In selection: Mapping > "+AWS_APP.stage+" > bootstrapped")
  print('Should be value: "true"')
  print('bootstrapped: "true"')
  print("###################################")

  AWS_CICD.copy_file_to_s3(
    file=DIR_APP+'code/cicd/cicd-infra-stage.template',
    s3_bucket=AWS_CICD.get_ssm_parameter('/'+AWS_CICD.prefix+'/artifactBucketName')+"-all",
    s3_object_path_with_file_name="cicd/"+AWS_APP.stage+"/cicd-infra-stage.template"
  )

  if AWS_CICD.getAccoundId() != AWS_APP.getAccoundId():
    AWS_APP.deploy_template(
        template_name=AWS_APP.prefix+"-global-cicd", 
        template_file=DIR_APP+'code/cicd/cicd.template',
        parameters_array={
          "stage":AWS_APP.stage,
          "projectName":f"/{AWS_APP.prefix}/projectName",
          "deploymentBucketName":f"/{AWS_APP.prefix}/deploymentBucketName",
          "artifactBucketName":f"/{AWS_APP.prefix}/artifactBucketName",
          "codePipelineSourceBucketName":f"/{AWS_APP.prefix}/codePipelineSourceBucketName",
          "sbxInfrastructureKeyId": "/sbx/infrastructureKeyId" if AWS_APP.stage == "sbx" else "none",
          "devInfrastructureKeyId": "/dev/infrastructureKeyId" if AWS_APP.stage == "dev" else "none",
          "qaInfrastructureKeyId": "/qa/infrastructureKeyId" if AWS_APP.stage == "qa" else "none",
          "prdInfrastructureKeyId": "/prd/infrastructureKeyId" if AWS_APP.stage == "prd" else "none",
          "crossAccountRequiments":"yes"
          },
        deploy_type="update"
    )

  AWS_CICD.deploy_template(
      template_name=AWS_CICD.prefix+"-global-cicd",
      template_file=DIR_APP+'code/cicd/cicd.template',
      parameters_array={
        "stage":AWS_CICD.stage,
        "sbxInfrastructureKeyId":"none",
        "devInfrastructureKeyId":"none",
        "qaInfrastructureKeyId":"/qa/infrastructureKeyId",
        "prdInfrastructureKeyId":"/prd/infrastructureKeyId",
        "crossAccountRequiments":"no"
        },
      deploy_type="update"
  )

def send_zips():
  AWS_CICD.copy_file_to_s3(
    file=DIR_APP+'code/cicd/cicd-infra-stage.template',
    s3_bucket=AWS_CICD.get_ssm_parameter('/'+AWS_CICD.prefix+'/artifactBucketName')+"-all",
    s3_object_path_with_file_name="cicd/"+AWS_APP.stage+"/cicd-infra-stage.template"
  )

  source_code_package_name = AWS_CICD.prefix+'-cicd.zip'
  AWS_CICD.create_deployment_package(package=source_code_package_name, dir_to_archive=DIR_APP+'code/cicd/')
  AWS_CICD.copy_file_to_s3(
    file=source_code_package_name,
    s3_bucket=AWS_APP.get_ssm_parameter('/'+AWS_CICD.prefix+'/codePipelineSourceBucketName')+"-all",
    s3_object_path_with_file_name=AWS_APP.stage+"/"+source_code_package_name
  )

  source_code_package_name = AWS_CICD.prefix+'-app.zip'
  AWS_CICD.create_deployment_package(package=source_code_package_name, dir_to_archive=DIR_APP+'code/app/')
  AWS_CICD.copy_file_to_s3(
    file=source_code_package_name,
    s3_bucket=AWS_APP.get_ssm_parameter('/'+AWS_CICD.prefix+'/codePipelineSourceBucketName')+"-all",
    s3_object_path_with_file_name=AWS_APP.stage+"/"+source_code_package_name
  )

init()
#!/usr/bin/env groovy

import groovy.json.JsonOutput
// Add whichever params you think you'd most want to have
// replace the slackURL below with the hook url provided by
// slack when you configure the webhook
def notifyGithub(state) {
    def githubURL = 'https://api.github.com/repos/cryoem/eman2/statuses'
    def payload = JsonOutput.toJson([state        : state,
                                     target_url   : "${BUILD_URL}",
                                     description  : "The build succeeded!",
                                     context      : "${JOB_NAME}"
                                     ])
    sh "curl -u eman-bot -X POST --data-urlencode \'payload=${payload}\' ${githubURL}"
}

pipeline {
  agent {
    node {
      label 'jenkins-slave-1'
    }
    
  }
  stages {
    stage('parallel_stuff') {
      parallel {
        stage('recipe') {
          steps {
            echo 'bash ci_support/build_recipe.sh'
          }
        }
        stage('no_recipe') {
          steps {
            echo 'source /bin/activate eman-env && bash ci_support/build_no_recipe.sh'
          }
        }
      }
    }
    stage('s') {
      steps {
        echo 'Hmmm'
      }
    }
  }
  environment {
    SKIP_UPLOAD = '1'
  }
  post {
    success {
      githubNotify(status: 'SUCCESS', description: 'Yay!', context: "${JOB_NAME}")
      
    }
    
    failure {
      githubNotify(status: 'FAILURE', description: 'Oops!', context: "${JOB_NAME}")
      
    }
    
  }
}
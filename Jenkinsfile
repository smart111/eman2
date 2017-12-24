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
        sh(curl -u "eman-bot" https://api.github.com/repos/cryoem/eman2/statuses/"${GIT_COMMIT}" \\
         -d \'\{
           "state": "success",
           "target_url": "${BUILD_URL}",
           "description": "The build succeeded!",
           "context": "${JOB_NAME}"
         \}\')
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
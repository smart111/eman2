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
            echo 'source ${HOME}/anaconda2/bin/activate eman-env && bash ci_support/build_no_recipe.sh'
          }
        }
      }
    }
  }
post {
    success {
        githubNotify(status: 'SUCCESS', description: 'Yay!', context: "${JOB_BASE_NAME}")
    }
    failure {
        githubNotify(status: 'FAILURE', description: 'Oops!', context: "${JOB_BASE_NAME}")
    }
}
  environment {
    SKIP_UPLOAD = '1'
  }
}
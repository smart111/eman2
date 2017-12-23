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
    stage('status') {
      steps {
        githubNotify(status: 'SUCCESS', description: 'Yay!', context: '${JOB_NAME}')
        githubNotify(status: 'FAILURE', description: 'Oops!')
      }
    }
  }
  environment {
    SKIP_UPLOAD = '1'
  }
}
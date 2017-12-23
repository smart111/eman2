pipeline {
  agent {
    node {
      label 'jenkins-slave-1'
    }
    
  }
  stages {
    stage('pending') {
      steps {
        githubNotify(status: 'PENDING', description: 'Building...', context: "${JOB_NAME}")
      }
    }
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
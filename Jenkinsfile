pipeline {
  agent {
    node {
      label 'jenkins-slave-1'
    }
    
  }
  stages {
    stage('notify') {
      steps {
        emailext(subject: 'Building job', body: 'Blank')
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
}
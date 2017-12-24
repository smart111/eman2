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
      //githubNotify(status: 'SUCCESS', description: 'Yay!', context: "${JOB_NAME}")
     // notifyGithub('success')
          step([$class: 'GitHubCommitStatusSetter', contextSource: [$class: 'ManuallyEnteredCommitContextSource', context: "${JOB_NAME}"], statusResultSource: [$class: 'ConditionalStatusResultSource', results: [[$class: 'AnyBuildResult', message: 'Build succeeded!', state: 'SUCCESS']]]])
    }
    
    failure {
      //githubNotify(status: 'FAILURE', description: 'Oops!', context: "${JOB_NAME}")
      step([$class: 'GitHubCommitStatusSetter', contextSource: [$class: 'ManuallyEnteredCommitContextSource', context: "${JOB_NAME}"], statusResultSource: [$class: 'ConditionalStatusResultSource', results: [[$class: 'AnyBuildResult', message: 'Oops!', state: 'FAILURE']]]])
      
    }
    
  }
}
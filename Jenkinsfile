def getJobType() {
    def causes = "${currentBuild.rawBuild.getCauses()}"
    def job_type = "UNKNOWN"
    
    if(causes ==~ /.*TimerTrigger.*/)    { job_type = "cron" }
    if(causes ==~ /.*GitHubPushCause.*/) { job_type = "push" }
    if(causes ==~ /.*UserIdCause.*/)     { job_type = "manual" }
    if(causes ==~ /.*ReplayCause.*/)     { job_type = "manual" }
    
    return job_type
}

def notifyGitHub(status) {
    if(JOB_TYPE == "push") {
        if(status == 'PENDING') { message = 'Building...' }
        if(status == 'SUCCESS') { message = 'Build succeeded!' }
        if(status == 'FAILURE') { message = 'Build failed!' }
        if(status == 'ERROR')   { message = 'Build aborted!' }
        step([$class: 'GitHubCommitStatusSetter', contextSource: [$class: 'ManuallyEnteredCommitContextSource', context: "JenkinsCI/${JOB_NAME}"], statusResultSource: [$class: 'ConditionalStatusResultSource', results: [[$class: 'AnyBuildResult', message: message, state: status]]]])
    }
}

def notifyEmail() {
    if(JOB_TYPE == "push") {
        emailext(recipientProviders: [[$class: 'DevelopersRecipientProvider']],  
                 subject: '[JenkinsCI/$PROJECT_NAME/push] ' + "($GIT_BRANCH_SHORT - ${GIT_COMMIT_SHORT})" + ' #$BUILD_NUMBER - $BUILD_STATUS!',
                 body: '''${SCRIPT, template="groovy-text.template"}''',
                 attachLog: true
                 )
    }
    
    if(JOB_TYPE == "cron") {
        emailext(to: '$DEFAULT_RECIPIENTS',
                 subject: '[JenkinsCI/$PROJECT_NAME/cron] ' + "($GIT_BRANCH_SHORT - ${GIT_COMMIT_SHORT})" + ' #$BUILD_NUMBER - $BUILD_STATUS!',
                 body: '''${SCRIPT, template="groovy-text.template"}''',
                 attachLog: true
                 )
    }
}

def isRelease() {
    return (GIT_BRANCH ==~ /.*\/release.*/) && (JOB_TYPE == "push")
}

def isCurrentRelease() {
    return true
}

def runCronJob() {
    sh 'echo ${BUILD_SCRIPTS_DIR}/cronjob.sh $STAGE_NAME v2.21'
    if(isCurrentRelease())
      sh "whoami && scp -v ${INSTALLERS_DIR}/eman2.win64.exe ${DEPLOY_DEST}/eman2.win.unstable.exe"
}

def setUploadFlag() {
    if(getJobType() == "cron") {
        return '0'
    } else {
        return '1'
    }
}

def resetBuildScripts() {
    if(JOB_TYPE == "cron" || isRelease())
        sh 'cd ${BUILD_SCRIPTS_DIR} && git checkout -f master'
}

def getHomeDir() {
    def result = ''
    if(SLAVE_OS == "win") {
        result = "${USERPROFILE}"
    }
    else {
        result = "${HOME}"
    }
    
    return result
}

pipeline {
  agent {
    node { label 'jenkins-slave-1' }
  }
  
  options {
    disableConcurrentBuilds()
    timestamps()
  }
  
  triggers {
    cron('0 3 * * *')
  }
  
  environment {
    SKIP_UPLOAD = setUploadFlag()
    JOB_TYPE = getJobType()
    GIT_BRANCH_SHORT = sh(returnStdout: true, script: 'echo ${GIT_BRANCH##origin/}').trim()
    GIT_COMMIT_SHORT = sh(returnStdout: true, script: 'echo ${GIT_COMMIT:0:7}').trim()
    HOME_DIR = getHomeDir()
    BUILD_SCRIPTS_DIR = "${HOME_DIR}/workspace/build-scripts-cron/"
    INSTALLERS_DIR = '${HOME_DIR}/workspace/${STAGE_NAME}-installers'
    DEPLOY_DEST    = 'zope@ncmi.grid.bcm.edu:/home/zope/zope-server/extdata/reposit/ncmi/software/counter_222/software_136/'
    NUMPY_VERSION='1.9'
    BUILD_SCRIPTS_BRANCH='jenkins-release-upload-win'
  }
  
  stages {
    // Stages triggered by GitHub pushes
    stage('notify-pending') {
      when {
        expression { JOB_TYPE == "push" }
      }
      
      steps {
        notifyGitHub('PENDING')
      }
    }
    
    stage('build') {
      when {
        not { expression { JOB_TYPE == "cron" } }
        not { expression { isRelease() } }
        not { expression { SLAVE_OS == "win" } }
      }
      
      parallel {
        stage('recipe') {
          steps {
            sh 'bash ci_support/build_recipe.sh'
          }
        }
        
        stage('no_recipe') {
          steps {
            sh 'source $(conda info --root)/bin/activate eman-env && bash ci_support/build_no_recipe.sh'
          }
        }
      }
    }
    
    // Stages triggered by cron or by a release branch
    stage('build-scripts-checkout') {
      when {
        anyOf {
          expression { JOB_TYPE == "cron" }
          expression { isRelease() }
        }
      }
      
      steps {
        sh 'cd ${BUILD_SCRIPTS_DIR} && git fetch --prune && (git checkout -f $BUILD_SCRIPTS_BRANCH || git checkout -t origin/$BUILD_SCRIPTS_BRANCH) && git pull --rebase'
      }
    }
    
    stage('win') {
      when {
        anyOf {
          expression { JOB_TYPE == "cron" }
          expression { isRelease() }
        }
        expression { SLAVE_OS == "win" }
      }
      
      steps {
        runCronJob()
      }
    }
  }
  
  post {
    success {
      notifyGitHub('SUCCESS')
    }
    
    failure {
      notifyGitHub('FAILURE')
    }
    
    aborted {
      notifyGitHub('ERROR')
    }
    
    always {
      notifyEmail()
      resetBuildScripts()
    }
  }
}

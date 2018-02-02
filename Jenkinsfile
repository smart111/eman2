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
}

def isRelease() {
    return GIT_BRANCH ==~ /.*\/release.*/
}

def isBuildBinary() {
    return true
}

def isRunCurrentStage(os_name) {
    return isBuildBinary() && SLAVE_OS == os_name
}

def runCronJob() {
    sh 'bash ${HOME_DIR}/workspace/build-scripts-cron/cronjob.sh $STAGE_NAME $GIT_BRANCH_SHORT'
    if(isBuildBinary() && SLAVE_OS != 'win')
      sh "rsync -avzh --stats ${INSTALLERS_DIR}/eman2.${STAGE_NAME}.sh ${DEPLOY_DEST}/eman2.${STAGE_NAME}.unstable.sh"
}

def setUploadFlag() {
    return '1'
}

def resetBuildScripts() {
    if(isBuildBinary())
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
    BUILD_SCRIPTS_BRANCH='jenkins-refactor'
  }
  
  stages {
    // Stages triggered by GitHub pushes
    stage('notify-pending') {
      steps {
        notifyGitHub('PENDING')
      }
    }
    
    stage('build') {
      when {
        not { expression { isRelease() } }
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
        expression { isBuildBinary() }
      }
      
      steps {
        sh 'cd ${BUILD_SCRIPTS_DIR} && git fetch --prune && (git checkout -f $BUILD_SCRIPTS_BRANCH || git checkout -t origin/$BUILD_SCRIPTS_BRANCH) && git pull --rebase'
      }
    }
    
    stage('centos6') {
      when {
        expression { isRunCurrentStage('linux') }
      }
      
      steps {
        runCronJob()
      }
    }
    
    stage('centos7') {
      when {
        expression { isRunCurrentStage('linux') }
      }
      
      steps {
        runCronJob()
      }
    }
    
    stage('mac') {
      when {
        expression { isRunCurrentStage('mac') }
      }
      environment {
        EMAN_TEST_SKIP=1
      }
      
      steps {
        runCronJob()
      }
    }
    
    stage('win') {
      when {
        expression { isRunCurrentStage('win') }
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

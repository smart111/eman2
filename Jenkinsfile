def getJobType() {
    def causes = "${currentBuild.rawBuild.getCauses()}"
    def job_type = "UNKNOWN"
    
    if(causes ==~ /.*TimerTrigger.*/)    { job_type = "cron" }
    if(causes ==~ /.*GitHubPushCause.*/) { job_type = "push" }
    if(causes ==~ /.*UserIdCause.*/)     { job_type = "manual" }
    if(causes ==~ /.*ReplayCause.*/)     { job_type = "manual" }
    
    //SCMTriggerCause
    //[job/github-triggers/375[com.cloudbees.jenkins.GitHubPushCause@3]]
    //[job/github-triggers/376[hudson.triggers.SCMTrigger$SCMTriggerCause@3]]
    
    return causes
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

def isSkip() {
    return git_commit_message ==~ /.*\[ci *skip\].*/
}

def runCronJob() {
    sh "bash ${HOME}/workspace/build-scripts-cron/cronjob.sh $STAGE_NAME"
    if(isRelease())
      sh "rsync -avzh --stats ${INSTALLERS_DIR}/eman2.${STAGE_NAME}.unstable.sh ${DEPLOY_DEST}"
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
        sh 'cd ${HOME}/workspace/build-scripts-cron/ && git checkout -f master'
}

def repoConfig() {
    checkout([$class: 'GitSCM', branches: [[name: '*/*']], doGenerateSubmoduleConfigurations: false, extensions: [[$class: 'PruneStaleBranch'], [$class: 'CleanBeforeCheckout'], [$class: 'MessageExclusion', excludedMessage: '(?s).*\\[skip jenkins\\].*']], submoduleCfg: [], userRemoteConfigs: [[url: 'repo']]])
}

pipeline {
  agent {
    node { label 'jenkins-slave-1' }
  }
  
  environment {
    git_commit_message = sh(returnStdout: true, script: 'git log -1 --pretty=%B').trim()
  }

  stages {
    //if()
    stage('notify-pending') {
      steps {
        script {
            if(isSkip())
                exit 0
        }
        echo '$git_commit_message'
        //echo isSkip()
        echo getJobType()
        sh 'env' 
      }
    }
  }
}

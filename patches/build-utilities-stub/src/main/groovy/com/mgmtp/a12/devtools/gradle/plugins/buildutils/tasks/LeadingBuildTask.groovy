package com.mgmtp.a12.devtools.gradle.plugins.buildutils.tasks

import org.gradle.api.DefaultTask
import org.gradle.process.ExecOperations

import javax.inject.Inject

/**
 * Minimal OSS-mirror reconstruction of LeadingBuildTask (real source stripped from the public
 * export). Consuming scripts register tasks of this type and call {@link #execCommandLine} inside
 * {@code doLast {}} to drive the Node/pnpm build.
 *
 * The Java artifacts do not depend on these tasks, so for a Java-only build they never execute.
 * The implementation is nonetheless faithful: when invoked it runs the given command in the
 * project directory, so the node side remains functional if explicitly requested.
 */
abstract class LeadingBuildTask extends DefaultTask {

    @Inject
    abstract ExecOperations getExecOperations()

    /** Run an external command line in the project directory, inheriting standard streams. */
    void execCommandLine(Object... commandLine) {
        List<String> args = commandLine.collect { it.toString() }
        File workingDir = project.projectDir
        getExecOperations().exec { spec ->
            spec.commandLine(args)
            spec.workingDir(workingDir)
        }
    }
}

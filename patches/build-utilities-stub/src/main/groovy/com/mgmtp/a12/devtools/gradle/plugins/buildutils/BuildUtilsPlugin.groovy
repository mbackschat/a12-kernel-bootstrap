package com.mgmtp.a12.devtools.gradle.plugins.buildutils

import org.gradle.api.Plugin
import org.gradle.api.Project

/**
 * Minimal OSS-mirror reconstruction of the build-utilities plugin.
 *
 * The real implementation source is intentionally stripped from the public a12-devtools export
 * (same pattern as the stripped kernel test suite). This stub reconstructs only the surface that
 * consuming build scripts (notably a12-base) reference, so those builds can configure and produce
 * their Java artifacts without contacting any private system.
 *
 * Consuming scripts use the helper/task classes directly via the buildscript classpath; nothing
 * applies this plugin, so apply() is effectively a no-op — it exists only so the declared
 * implementationClass resolves and java-gradle-plugin validation passes.
 */
class BuildUtilsPlugin implements Plugin<Project> {
    @Override
    void apply(Project project) {
        project.logger.info('[build-utilities OSS stub] applied; node-orchestration helpers are inert')
    }
}

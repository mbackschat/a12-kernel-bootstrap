package com.mgmtp.a12.devtools.gradle.plugins.buildutils.tasks

import org.gradle.api.DefaultTask
import org.gradle.api.tasks.Internal
import org.gradle.api.tasks.TaskAction

/**
 * Minimal OSS-mirror reconstruction of PackageJsonModifierTask (real source stripped from the public
 * export). Holds the properties consuming scripts set ({@code packageDirs}, {@code change}). The Java
 * build does not need it to run; the action is a best-effort no-op describing what it would do.
 *
 * Getters are explicitly annotated {@code @Internal} so java-gradle-plugin's plugin validation passes.
 */
abstract class PackageJsonModifierTask extends DefaultTask {

    private List<Object> packageDirs = []
    private Object change

    @Internal
    List<Object> getPackageDirs() { return packageDirs }
    void setPackageDirs(List<Object> packageDirs) { this.packageDirs = packageDirs }

    @Internal
    Object getChange() { return change }
    void setChange(Object change) { this.change = change }

    @TaskAction
    void modify() {
        logger.lifecycle("[build-utilities OSS stub] PackageJsonModifierTask: change=${change} over " +
                "${packageDirs?.size() ?: 0} dir(s) (no-op in OSS build)")
    }
}

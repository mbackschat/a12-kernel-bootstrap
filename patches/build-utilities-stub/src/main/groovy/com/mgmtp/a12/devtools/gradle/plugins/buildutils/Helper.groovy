package com.mgmtp.a12.devtools.gradle.plugins.buildutils

import groovy.json.JsonSlurper

/**
 * Minimal OSS-mirror reconstruction of the build-utilities Helper (real source stripped from the
 * public export). Provides only the static surface used by consuming build scripts.
 */
class Helper {

    /**
     * Resolve the project version. An explicit version property wins; otherwise the {@code version}
     * field of the given package.json is used; falls back to {@code 0.0.0-SNAPSHOT}.
     *
     * @param packageJson     the module's package.json (source of truth for the version)
     * @param versionProperty value of the Gradle {@code version} project property (or null/"unspecified")
     * @param useProperty     value of the Gradle {@code use} project property (unused in this stub)
     */
    static String getVersion(File packageJson, Object versionProperty, Object useProperty) {
        String explicit = versionProperty?.toString()?.trim()
        if (explicit && explicit != 'unspecified') {
            return explicit
        }
        if (packageJson?.exists()) {
            def json = new JsonSlurper().parse(packageJson)
            if (json?.version) {
                return json.version.toString()
            }
        }
        return '0.0.0-SNAPSHOT'
    }

    /**
     * Describe a "set version" change consumed by {@link tasks.PackageJsonModifierTask}. The value is
     * opaque to the build script; in this stub it is simply the target version string.
     */
    static Object createSetVersion(Object version) {
        return version?.toString()
    }
}

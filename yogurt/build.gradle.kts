@file:OptIn(ExperimentalKotlinGradlePluginApi::class)

import com.codingfeline.buildkonfig.compiler.FieldSpec
import org.jetbrains.kotlin.gradle.ExperimentalKotlinGradlePluginApi
import org.jetbrains.kotlin.gradle.plugin.mpp.KotlinNativeTarget
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

plugins {
    id("buildsrc.convention.kotlin-multiplatform")
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.build.konfig)
    alias(libs.plugins.kotlinx.atomicfu)
}

version = "0.1.0"

kotlin {
    applyDefaultHierarchyTemplate {
        common {
            group("posix") {
                withLinux()
                withMacos()
            }
        }
    }

    sourceSets {
        commonMain.dependencies {
            implementation(project(":acidify-core"))
            implementation(project(":acidify-milky"))
            implementation(libs.kotlinx.datetime)
            implementation(libs.bundles.ktor.client)
            implementation(libs.bundles.ktor.server)
            implementation(libs.ktor.serialization.kotlinx.json)
            implementation(libs.acidify.codec)
            implementation(libs.ktfs)
            implementation(libs.qr.matrix)
            implementation(libs.quickjs.kt)
            implementation(libs.mordant)
        }
        findByName("jvmMain")?.dependencies {
            implementation(libs.ktor.client.java)
            implementation(libs.logback.classic)
        }
        findByName("mingwMain")?.dependencies {
            implementation(libs.ktor.client.winhttp)
        }
        findByName("appleMain")?.dependencies {
            implementation(libs.ktor.client.darwin)
        }
        findByName("linuxMain")?.dependencies {
            implementation(libs.ktor.client.curl)
        }
    }

    targets.withType<KotlinNativeTarget> {
        binaries {
            executable {
                entryPoint = "org.ntqqrev.yogurt.main"
                baseName = "rizify"
            }
        }
    }

    targets.withType<KotlinNativeTarget>().matching { it.name == "mingwX64" }.configureEach {
        binaries.all {
            linkerOpts(
                "-Wl,-Bstatic",
                "-lstdc++",
                "-lgcc",
                "-Wl,-Bdynamic",
            )
        }
    }
}

val gitHashProvider: Provider<String> = providers.exec {
    commandLine("git", "rev-parse", "HEAD")
    isIgnoreExitValue = true
}.let { exec ->
    exec.standardOutput.asText.zip(exec.result) { output, result ->
        if (result.exitValue == 0) output.trim().ifEmpty { "unknown" } else "unknown"
    }
}

val coreLibGitHashProvider: Provider<String> = providers.exec {
    commandLine("git", "-C", project(":acidify-core").projectDir.absolutePath, "rev-parse", "HEAD")
    isIgnoreExitValue = true
}.let { exec ->
    exec.standardOutput.asText.zip(exec.result) { output, result ->
        if (result.exitValue == 0) output.trim().ifEmpty { "unknown" } else "unknown"
    }
}

val buildTimeProvider: Provider<String> = providers.provider {
    ZonedDateTime.now(ZoneId.of("Asia/Shanghai"))
        .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss z"))
}

val runNumberProvider: Provider<String> = providers.provider {
    System.getenv("GITHUB_RUN_NUMBER") ?: "local"
}

buildkonfig {
    packageName = "org.ntqqrev.yogurt"

    defaultConfigs {
        buildConfigField(FieldSpec.Type.STRING, "name", "Rizify")
        buildConfigField(FieldSpec.Type.STRING, "version", project.version.toString())
        buildConfigField(
            FieldSpec.Type.STRING,
            "coreVersion",
            project(":acidify-core").let {
                "${it.name} ${it.version}+${coreLibGitHashProvider.get().take(7)}"
            }
        )
        buildConfigField(FieldSpec.Type.STRING, "commitHash", gitHashProvider.get())
        buildConfigField(FieldSpec.Type.STRING, "buildTime", buildTimeProvider.get())
    }
}

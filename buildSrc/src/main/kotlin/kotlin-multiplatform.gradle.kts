package buildsrc.convention

plugins {
    kotlin("multiplatform")
}

kotlin {
    val actionsTarget = System.getenv("GITHUB_ACTIONS_BUILD_TARGET")
    when (actionsTarget) {
        // is run from GitHub Actions - build Yogurt, improving dependency pulling time
        "jvm" -> jvm()
        "mingwX64" -> mingwX64()
        "macosArm64" -> macosArm64()
        "linuxX64" -> linuxX64()
        "linuxArm64" -> linuxArm64()
        "all" -> {
            jvm()
            mingwX64()
            macosArm64()
            linuxX64()
            linuxArm64()
        }

        // Local builds only need the JVM metadata target and the Linux native target.
        // Keeping the other native targets behind an explicit switch avoids pulling
        // unavailable SDKs and metadata variants on Linux.
        null, "" -> {
            jvm()
            linuxX64()
        }

        else -> error("不支持的 GITHUB_ACTIONS_BUILD_TARGET=$actionsTarget")
    }

    jvmToolchain(25)
}

import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

val keystorePropsFile = rootProject.file("keystore/keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) {
        keystorePropsFile.inputStream().use { load(it) }
    }
}
val hasReleaseKeystore = keystoreProps.getProperty("storeFile")?.let {
    rootProject.file(it).exists()
} == true

android {
    namespace = "dev.mrksvt.reelsdownloader"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.mrksvt.reelsdownloader"
        minSdk = 26
        targetSdk = 36
        versionCode = 9
        versionName = "0.1.8"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("arm64-v8a")
        }
    }

    signingConfigs {
        if (hasReleaseKeystore) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (hasReleaseKeystore) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    // Locale config dibuat manual via res/xml/locales_config.xml (lihat AndroidManifest).
    // auto-generate butuh resources.properties yang tidak ada di repo ini.

    packaging {
        resources {
            excludes += setOf(
                "/META-INF/{AL2.0,LGPL2.1}",
                "META-INF/DEPENDENCY",
                "META-INF/LICENSE*",
                "META-INF/NOTICE*",
            )
        }
        jniLibs {
            // youtubedl-android meng-`exec` libpython/libffmpeg langsung dari
            // ApplicationInfo.nativeLibraryDir. Dengan packAging default AGP 8.x
            // (extractNativeLibs=false), path itu TIDAK ada di disk sehingga
            // YoutubeDL.init() gagal "failed to initialize". Legacy packaging
            // memaksa .so diekstrak ke nativeLibraryDir saat install.
            useLegacyPackaging = true
        }
    }

    lint {
        abortOnError = true
        warningsAsErrors = false
        disable += "GradleDependency"
    }

    // Skema Room di-export supaya migrasi bisa diuji (A17-0) dan perubahannya
    // terlihat di diff, bukan tersembunyi.
    ksp {
        arg("room.schemaLocation", "$projectDir/schemas")
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.kotlinx.coroutines.android)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.material3)

    implementation(libs.youtubedl.android)
    implementation(libs.youtubedl.ffmpeg)

    ksp(libs.androidx.room.compiler)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    // Test migrasi Room berjalan di JVM memakai SQLite asli (bukan emulator),
    // karena perangkat tidak bisa dipakai untuk `connectedAndroidTest` di sini.
    testImplementation(libs.sqlite.jdbc)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
}

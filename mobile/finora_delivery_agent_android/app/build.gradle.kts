plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "iq.finora.deliveryagent"
    compileSdk = 34

    defaultConfig {
        applicationId = "iq.finora.deliveryagent"
        minSdk = 24
        targetSdk = 34
        versionCode = 5
        versionName = "1.1.3"
        buildConfigField("String", "DEFAULT_BASE_URL", "\"https://www.finora.company\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Internal distribution: sign release with the debug keystore so phones can install it.
            signingConfig = signingConfigs.getByName("debug")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
}

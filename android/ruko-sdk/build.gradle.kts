// RUKO SDK: everything a UPI app needs to check a payment for scams on the phone and with the
// RUKO server. Cache Pay (:app) is its first user. See android/README.md "Integrate RUKO".
plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.ruko.sdk"
    compileSdk = 37

    defaultConfig {
        minSdk = 26
        buildConfigField("String", "SDK_VERSION", "\"0.1.0\"")
        consumerProguardFiles("consumer-rules.pro")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    api(libs.androidx.work.runtime.ktx)
    api(platform(libs.androidx.compose.bom))
    api(libs.androidx.compose.runtime) // observable state the host's UI can read (no Compose UI here)

    api(libs.retrofit)
    api(libs.retrofit.kotlinx.serialization)
    api(libs.kotlinx.serialization.json)

    testImplementation(libs.junit)
}

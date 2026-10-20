import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// PAYEE_SALT and API_BASE_URL come from local.properties, which is never committed.
// PAYEE_SALT must equal the backend's .env value or the demo payee will look brand new.
val localProps = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

android {
    namespace = "com.ruko.demo"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.ruko.demo"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0-finale"

        buildConfigField("String", "PAYEE_SALT", "\"${localProps.getProperty("PAYEE_SALT", "")}\"")
        buildConfigField(
            "String",
            "API_BASE_URL",
            "\"${localProps.getProperty("API_BASE_URL", "http://localhost:8000/")}\""
        )
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.kotlinx.serialization.json)

    testImplementation(libs.junit)
}

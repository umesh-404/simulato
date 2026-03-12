# Simulato ProGuard Rules
-keepattributes Signature
-keepattributes *Annotation*

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }

# Gson
-keep class com.simulato.app.networking.** { *; }
-keep class com.simulato.app.shared.** { *; }

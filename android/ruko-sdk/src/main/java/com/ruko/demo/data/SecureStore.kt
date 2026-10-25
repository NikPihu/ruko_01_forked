package com.ruko.demo.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.core.util.AtomicFile
import java.io.File
import java.io.IOException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Encrypted files in the app's private, no-backup folder.
 *
 * Each file is AES-256-GCM encrypted with a key that lives in the Android Keystore
 * (hardware backed where the phone has it) and can never be exported. Other apps cannot
 * read the folder, and it is left out of cloud backup and device transfer.
 */
class SecureStore(private val dir: File) {

    init {
        dir.mkdirs()
    }

    fun write(name: String, plain: ByteArray) {
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.iv + cipher.doFinal(plain)
        val file = AtomicFile(File(dir, name))
        val stream = file.startWrite()
        try {
            stream.write(sealed)
            file.finishWrite(stream)
        } catch (e: IOException) {
            file.failWrite(stream)
            throw e
        }
    }

    /** Decrypted bytes, or null when the file does not exist. */
    fun read(name: String): ByteArray? {
        val file = AtomicFile(File(dir, name))
        if (!file.baseFile.exists()) return null
        val sealed = file.readFully()
        val cipher = Cipher.getInstance(TRANSFORMATION).apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, sealed, 0, IV_BYTES))
        }
        return cipher.doFinal(sealed, IV_BYTES, sealed.size - IV_BYTES)
    }

    fun delete(name: String) {
        AtomicFile(File(dir, name)).delete()
    }

    /** Deleting the key makes any leftover copy of the files unreadable. */
    fun deleteKey() {
        keyStore().deleteEntry(KEY_ALIAS)
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private fun key(): SecretKey {
        (keyStore().getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "cachepay_account_key"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
        const val TAG_BITS = 128
    }
}

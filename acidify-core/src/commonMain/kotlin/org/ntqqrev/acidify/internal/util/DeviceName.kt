package org.ntqqrev.acidify.internal.util

import org.ntqqrev.acidify.internal.crypto.hash.SHA256

internal const val LEGACY_DEVICE_NAME_PREFIX = "Lagrange-"

internal fun generateRizifyDeviceName(guid: ByteArray): String {
    require(guid.isNotEmpty()) { "Device GUID must not be empty" }
    val digestId = SHA256.hash(guid).toHexString().lowercase()
    return "流转者-$digestId"
}

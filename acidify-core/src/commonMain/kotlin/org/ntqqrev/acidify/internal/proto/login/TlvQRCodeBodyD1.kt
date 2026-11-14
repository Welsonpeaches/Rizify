package org.ntqqrev.acidify.internal.proto.login

import kotlinx.serialization.Serializable
import kotlinx.serialization.EncodeDefault
import kotlinx.serialization.protobuf.ProtoNumber

@Serializable
internal class TlvQRCodeBodyD1Req(
    @ProtoNumber(1) val system: System = System(),
    @ProtoNumber(4) val genInfo: GenInfo = GenInfo(),
) {
    @Serializable
    internal class System(
        @ProtoNumber(1) val os: String = "",
        @ProtoNumber(2) val deviceName: String = "",
    )

    @Serializable
    internal class GenInfo(
        @ProtoNumber(3) val clientAppid: Int = 0,
        @EncodeDefault
        @ProtoNumber(6) val field6: Int = 1,
    )
}

@Serializable
internal class TlvQRCodeBodyD1LegacyReq(
    @ProtoNumber(1) val system: LegacySystem = LegacySystem(),
    @ProtoNumber(4) val typeBuf: ByteArray = byteArrayOf(),
) {
    @Serializable
    internal class LegacySystem(
        @ProtoNumber(1) val os: String = "",
        @ProtoNumber(2) val deviceName: String = "",
    )
}

@Serializable
internal class TlvQRCodeBodyD1Resp(
    @ProtoNumber(2) val qrCodeUrl: String = "",
    @ProtoNumber(3) val qrCodeString: String = "",
)

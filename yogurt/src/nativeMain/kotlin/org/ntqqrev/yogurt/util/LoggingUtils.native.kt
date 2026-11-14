package org.ntqqrev.yogurt.util

import io.ktor.util.logging.LogLevel as KtorLogLevel
import io.ktor.util.logging.Logger as KtorLogger
import org.ntqqrev.acidify.logging.LogHandler
import org.ntqqrev.acidify.logging.LogLevel
import org.ntqqrev.yogurt.YogurtApp
import org.ntqqrev.yogurt.YogurtApp.t

actual val YogurtApp.logHandler: LogHandler by lazy {
    LogHandler { level, tag, message, throwable ->
        t.println(
            formatColoredLog(
                level,
                tag,
                message,
                throwable?.stackTraceToString()
            )
        )
    }
}

actual fun YogurtApp.createKtorLogger(name: String): KtorLogger =
    object : KtorLogger {
        override val level: KtorLogLevel
            get() = when (config.logging.coreLogLevel) {
                LogLevel.VERBOSE -> KtorLogLevel.TRACE
                LogLevel.DEBUG -> KtorLogLevel.DEBUG
                LogLevel.INFO -> KtorLogLevel.INFO
                LogLevel.WARN -> KtorLogLevel.WARN
                LogLevel.ERROR -> KtorLogLevel.ERROR
            }

        private fun emit(logLevel: LogLevel, message: String, cause: Throwable? = null) {
            if (config.logging.coreLogLevel <= logLevel) {
                t.println(
                    formatColoredLog(
                        logLevel,
                        name,
                        message,
                        cause?.stackTraceToString()
                    )
                )
            }
        }

        override fun trace(message: String) = emit(LogLevel.VERBOSE, message)
        override fun trace(message: String, cause: Throwable) = emit(LogLevel.VERBOSE, message, cause)
        override fun debug(message: String) = emit(LogLevel.DEBUG, message)
        override fun debug(message: String, cause: Throwable) = emit(LogLevel.DEBUG, message, cause)
        override fun info(message: String) = emit(LogLevel.INFO, message)
        override fun info(message: String, cause: Throwable) = emit(LogLevel.INFO, message, cause)
        override fun warn(message: String) = emit(LogLevel.WARN, message)
        override fun warn(message: String, cause: Throwable) = emit(LogLevel.WARN, message, cause)
        override fun error(message: String) = emit(LogLevel.ERROR, message)
        override fun error(message: String, cause: Throwable) = emit(LogLevel.ERROR, message, cause)
    }

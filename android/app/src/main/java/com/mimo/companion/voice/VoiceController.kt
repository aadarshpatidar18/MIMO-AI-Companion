package com.mimo.companion.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale
import java.util.UUID

sealed interface VoiceState {
    data object Idle : VoiceState
    data object Listening : VoiceState
    data class Heard(val partial: String) : VoiceState
    data object Thinking : VoiceState
    data object Speaking : VoiceState
    data class Unavailable(val reason: String) : VoiceState
}

/**
 * Voice on the phone uses the phone's own engines (`SpeechRecognizer` and `TextToSpeech`), which are
 * already on the device, work offline on most modern phones, and add no download. The heavy
 * Whisper/Kokoro stack belongs on the PC (see docs/VOICE.md) where the RAM and the microphone array
 * are; a 200 MB model on a phone's battery for a push-to-talk button is the wrong trade.
 *
 * Nothing here records in the background: recognition only runs between [startListening] and the
 * recogniser's own stop, which is the length of one press.
 */
class VoiceController(private val context: Context) {

    private val _state = MutableStateFlow<VoiceState>(VoiceState.Idle)
    val state: StateFlow<VoiceState> = _state.asStateFlow()

    private var recogniser: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private val utteranceId = "mimo-${UUID.randomUUID()}"
    private var onFinal: ((String) -> Unit)? = null

    fun initialise() {
        if (tts == null) {
            tts = TextToSpeech(context) { status ->
                ttsReady = status == TextToSpeech.SUCCESS
                if (ttsReady) {
                    tts?.language = Locale.getDefault()
                    tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(id: String?) {
                            _state.value = VoiceState.Speaking
                        }

                        override fun onDone(id: String?) {
                            _state.value = VoiceState.Idle
                        }

                        @Deprecated("Deprecated in Java")
                        override fun onError(id: String?) {
                            _state.value = VoiceState.Idle
                        }
                    })
                }
            }
        }
    }

    fun startListening(onFinalText: (String) -> Unit) {
        if (!SpeechRecognizer.isRecognitionAvailable(context)) {
            _state.value = VoiceState.Unavailable("This phone has no speech recognition engine.")
            return
        }
        stopSpeaking()
        onFinal = onFinalText
        recogniser?.destroy()
        recogniser = SpeechRecognizer.createSpeechRecognizer(context).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    _state.value = VoiceState.Listening
                }

                override fun onBeginningOfSpeech() = Unit
                override fun onRmsChanged(rmsdB: Float) = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() = Unit

                override fun onError(error: Int) {
                    _state.value = VoiceState.Unavailable(describe(error))
                }

                override fun onResults(results: Bundle?) {
                    val text = results
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        .orEmpty()
                    _state.value = VoiceState.Idle
                    if (text.isNotBlank()) onFinal?.invoke(text)
                }

                override fun onPartialResults(partialResults: Bundle?) {
                    val text = partialResults
                        ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        .orEmpty()
                    if (text.isNotBlank()) _state.value = VoiceState.Heard(text)
                }

                override fun onEvent(eventType: Int, params: Bundle?) = Unit
            })
            val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            }
            startListening(intent)
        }
        _state.value = VoiceState.Listening
    }

    fun stopListening() {
        recogniser?.stopListening()
        _state.value = VoiceState.Idle
    }

    fun speak(text: String) {
        initialise()
        val engine = tts
        if (!ttsReady || engine == null) {
            _state.value = VoiceState.Unavailable("Text to speech is not ready on this phone.")
            return
        }
        engine.stop()
        engine.speak(text.take(1200), TextToSpeech.QUEUE_FLUSH, null, utteranceId)
    }

    fun stopSpeaking() {
        tts?.stop()
        if (_state.value == VoiceState.Speaking) _state.value = VoiceState.Idle
    }

    fun setThinking() {
        _state.value = VoiceState.Thinking
    }

    fun release() {
        recogniser?.destroy()
        recogniser = null
        tts?.shutdown()
        tts = null
        ttsReady = false
    }

    private fun describe(error: Int): String = when (error) {
        SpeechRecognizer.ERROR_AUDIO -> "The microphone was busy."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission was refused."
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT ->
            "Speech recognition needs a network on this phone."
        SpeechRecognizer.ERROR_NO_MATCH -> "I did not catch that."
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Speech recognition is already running."
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "No speech was heard."
        else -> "Speech recognition stopped (code $error)."
    }
}

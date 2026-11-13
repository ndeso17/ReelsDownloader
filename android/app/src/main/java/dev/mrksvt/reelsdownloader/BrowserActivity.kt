package dev.mrksvt.reelsdownloader

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.mrksvt.reelsdownloader.domain.ResultType
import dev.mrksvt.reelsdownloader.domain.UrlValidator
import dev.mrksvt.reelsdownloader.ui.icons.AppIcons
import dev.mrksvt.reelsdownloader.ui.theme.ReelsDownloaderTheme
import dev.mrksvt.reelsdownloader.ui.vm.BrowserCandidate
import dev.mrksvt.reelsdownloader.ui.vm.BrowserMessage
import dev.mrksvt.reelsdownloader.ui.vm.BrowserViewModel
import android.text.format.Formatter

/**
 * Browser mini berbasis WebView (A17-6).
 *
 * Menampilkan halaman apa adanya, lalu memantau request yang lewat untuk
 * menemukan tautan media langsung. Ini pengganti realistis dari cara kerja
 * 1DM/XDM di desktop (lihat docs/PLAN-BACKUP-ENGINE.md §2): Android tidak
 * mengizinkan membaca lalu lintas browser lain, jadi penangkapan dilakukan di
 * WebView milik aplikasi sendiri.
 */
class BrowserActivity : ComponentActivity() {

    private val viewModel: BrowserViewModel by viewModels()

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Hanya URL yang didukung yang boleh dibuka; selain itu ditolak supaya
        // aplikasi tidak berubah menjadi browser umum.
        val rawUrl = intent?.getStringExtra(EXTRA_URL)
        val url = UrlValidator.validate(rawUrl)
        val startUrl = (url as? UrlValidator.ValidationResult.Valid)?.url

        setContent {
            ReelsDownloaderTheme {
                if (startUrl == null) {
                    UntrustedScreen(onClose = { finish() })
                } else {
                    BrowserScreen(
                        startUrl = startUrl,
                        viewModel = viewModel,
                        onClose = { finish() },
                    )
                }
            }
        }
    }

    companion object {
        const val EXTRA_URL = "extra_url"
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BrowserScreen(
    startUrl: String,
    viewModel: BrowserViewModel,
    onClose: () -> Unit,
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbar = remember { SnackbarHostState() }
    val context = LocalContext.current
    val webView = remember { WebView(context) }

    LaunchedEffect(state.message) {
        val message = state.message ?: return@LaunchedEffect
        val text = when (message) {
            BrowserMessage.Queued -> context.getString(R.string.browser_queued)
            BrowserMessage.Untrusted -> context.getString(R.string.browser_untrusted)
            BrowserMessage.Failed -> context.getString(R.string.err_download_failed)
            BrowserMessage.NotMedia -> context.getString(R.string.browser_not_media)
        }
        snackbar.showSnackbar(text)
        viewModel.clearMessage()
    }

    androidx.compose.foundation.layout.Box(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            Scaffold(
                topBar = {
                    TopAppBar(
                        title = {
                            Text(
                                text = state.pageUrl.ifBlank { stringResource(R.string.browser_title) },
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                style = MaterialTheme.typography.titleSmall,
                            )
                        },
                        navigationIcon = {
                            IconButton(
                                onClick = {
                                    if (webView.canGoBack()) webView.goBack() else onClose()
                                },
                            ) {
                                Icon(
                                    imageVector = AppIcons.Close,
                                    contentDescription = stringResource(R.string.browser_close),
                                )
                            }
                        },
                        actions = {
                            IconButton(onClick = viewModel::clearCandidates) {
                                Icon(
                                    imageVector = AppIcons.Refresh,
                                    contentDescription = stringResource(R.string.browser_refresh),
                                )
                            }
                        },
                    )
                },
                snackbarHost = { SnackbarHost(snackbar) },
            ) { padding ->
                Column(modifier = Modifier.padding(padding)) {
                    // Halaman memakai sisa ruang; daftar kandidat muncul di
                    // bawahnya sehingga video tetap bisa diputar sambil memilih.
                    WebContent(
                        webView = webView,
                        startUrl = startUrl,
                        viewModel = viewModel,
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f),
                    )

                    if (state.loading) {
                        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                    }

                    CandidatePanel(
                        state = state,
                        onDownload = viewModel::download,
                    )
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun WebContent(
    webView: WebView,
    startUrl: String,
    viewModel: BrowserViewModel,
    modifier: Modifier = Modifier,
) {
    AndroidView(
        modifier = modifier,
        factory = {
            webView.apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.mediaPlaybackRequiresUserGesture = false
                settings.cacheMode = WebSettings.LOAD_DEFAULT
                // Tanpa ini, banyak halaman media gagal memuat di WebView.
                settings.userAgentString = settings.userAgentString
                    .replace("; wv", "")

                webViewClient = SniffingClient(viewModel)
                // Jembatan sempit: hanya menerima URL untuk dipindai, tidak
                // memberi halaman akses ke API lain.
                addJavascriptInterface(MediaScanBridge(viewModel), "MediaScan")
                loadUrl(startUrl)
            }
        },
        onRelease = { it.destroy() },
    )
}

/**
 * `WebViewClient` yang membaca setiap request tanpa mengubah responsnya.
 *
 * Mengembalikan `null` berarti WebView melanjutkan sendiri — penting supaya
 * pemutaran video tetap normal.
 */
private class SniffingClient(
    private val viewModel: BrowserViewModel,
) : WebViewClient() {

    override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
        url?.let(viewModel::onPageChanged)
        super.onPageStarted(view, url, favicon)
    }

    override fun onPageFinished(view: WebView, url: String?) {
        url?.let(viewModel::onPageFinished)
        super.onPageFinished(view, url)
        // `shouldInterceptRequest` hanya memberi URL (tanpa header), jadi video
        // dari CDN tanpa ekstensi bisa lolos. Pemeriksaan DOM + performance API
        // menangkapnya, termasuk `currentSrc` yang baru terisi setelah diputar.
        view.evaluateJavascript(DOM_SCAN_SCRIPT, null)
    }

    override fun shouldInterceptRequest(
        view: WebView,
        request: WebResourceRequest,
    ): WebResourceResponse? {
        val url = request.url.toString()
        val pageUrl = view.url.orEmpty()
        viewModel.onRequest(
            url = url,
            contentType = null,
            contentLength = null,
            pageUrl = pageUrl,
        )
        return null
    }

    private companion object {
        /**
         * Kumpulkan URL media yang benar-benar dipakai halaman.
         *
         * Skrip ini hanya membaca DOM dan performance entries milik halaman
         * itu sendiri; tidak menyentuh data pengguna.
         */
        val DOM_SCAN_SCRIPT = """
            (function () {
              try {
                var out = [];
                document.querySelectorAll('video, audio, source').forEach(function (el) {
                  if (el.currentSrc) out.push(el.currentSrc);
                  if (el.src) out.push(el.src);
                  var kids = el.querySelectorAll ? el.querySelectorAll('source') : [];
                  kids.forEach(function (s) { if (s.src) out.push(s.src); });
                });
                try {
                  performance.getEntriesByType('resource').forEach(function (e) {
                    var name = e.name || '';
                    var kind = e.initiatorType || '';
                    if (/video|audio/i.test(kind) || /\.(mp4|m4a|webm|m3u8|mp3|aac)(\?|#|$)/i.test(name)) {
                      out.push(name);
                    }
                  });
                } catch (ignored) {}
                if (window.MediaScan && window.MediaScan.push) {
                  out.forEach(function (u) { window.MediaScan.push(u); });
                }
              } catch (ignored) {}
            })();
        """.trimIndent()
    }
}

/**
 * Jembatan JavaScript → ViewModel untuk hasil pemindaian DOM.
 *
 * Sengaja hanya punya satu metode tanpa nilai balik, supaya halaman tidak bisa
 * memakai jembatan ini untuk hal lain.
 */
private class MediaScanBridge(private val viewModel: BrowserViewModel) {

    @android.webkit.JavascriptInterface
    fun push(url: String?) {
        val value = url?.takeIf { it.startsWith("http") } ?: return
        viewModel.onRequest(
            url = value,
            contentType = null,
            contentLength = null,
            pageUrl = viewModel.state.value.pageUrl,
        )
    }
}

@Composable
private fun CandidatePanel(
    state: dev.mrksvt.reelsdownloader.ui.vm.BrowserUiState,
    onDownload: (BrowserCandidate) -> Unit,
) {
    val context = LocalContext.current

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Text(
            text = if (state.candidates.isEmpty()) {
                stringResource(R.string.browser_hint)
            } else {
                stringResource(R.string.browser_found, state.candidates.size)
            },
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (state.candidates.isEmpty()) return@Column

        Spacer(Modifier.height(6.dp))
        LazyColumn(
            modifier = Modifier.height(180.dp),
            contentPadding = PaddingValues(vertical = 2.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            items(state.candidates, key = { it.key }) { candidate ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(start = 10.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            imageVector = if (candidate.type == ResultType.VIDEO) {
                                AppIcons.Movie
                            } else {
                                AppIcons.MusicNote
                            },
                            contentDescription = null,
                            modifier = Modifier.size(20.dp),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Spacer(Modifier.width(8.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = buildString {
                                    append(
                                        stringResource(
                                            if (candidate.type == ResultType.VIDEO) {
                                                R.string.browser_item_type_video
                                            } else {
                                                R.string.browser_item_type_audio
                                            }
                                        )
                                    )
                                    candidate.mimeType?.let { append(" · ").append(it) }
                                    if (candidate.isStream) {
                                        append(" · ").append(
                                            stringResource(R.string.browser_item_stream)
                                        )
                                    }
                                },
                                style = MaterialTheme.typography.labelMedium,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = candidate.contentLength?.let {
                                    Formatter.formatShortFileSize(context, it)
                                } ?: stringResource(R.string.browser_size_unknown),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                            )
                        }
                        Spacer(Modifier.width(6.dp))
                        Button(onClick = { onDownload(candidate) }) {
                            Text(stringResource(R.string.browser_download))
                        }
                    }
                }
            }
        }
    }
}

/** Layar untuk URL yang tidak didukung: jelas, tanpa WebView. */
@Composable
private fun UntrustedScreen(onClose: () -> Unit) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(
                imageVector = AppIcons.Error,
                contentDescription = null,
                modifier = Modifier.size(48.dp),
                tint = MaterialTheme.colorScheme.error,
            )
            Spacer(Modifier.height(12.dp))
            Text(
                text = stringResource(R.string.browser_untrusted),
                style = MaterialTheme.typography.bodyLarge,
            )
            Spacer(Modifier.height(16.dp))
            Button(onClick = onClose) {
                Text(stringResource(R.string.browser_close))
            }
        }
    }
}

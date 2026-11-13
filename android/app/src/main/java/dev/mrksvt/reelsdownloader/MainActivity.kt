package dev.mrksvt.reelsdownloader

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.mrksvt.reelsdownloader.data.AppSettings
import dev.mrksvt.reelsdownloader.ui.screen.HistoryScreen
import dev.mrksvt.reelsdownloader.ui.screen.HomeScreen
import dev.mrksvt.reelsdownloader.ui.screen.SettingsScreen
import dev.mrksvt.reelsdownloader.ui.theme.ReelsDownloaderTheme
import dev.mrksvt.reelsdownloader.ui.vm.HistoryEvent
import dev.mrksvt.reelsdownloader.ui.vm.HistoryViewModel
import dev.mrksvt.reelsdownloader.ui.vm.HomeViewModel
import dev.mrksvt.reelsdownloader.ui.vm.SettingsViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import dev.mrksvt.reelsdownloader.ui.icons.AppIcons

class MainActivity : ComponentActivity() {

    /** URL dari share sheet, dikonsumsi sekali oleh HomeViewModel. */
    private val sharedUrl = MutableStateFlow<String?>(null)

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleIntent(intent)

        setContent {
            val container = (application as ReelsDownloaderApp).container
            val settings by container.settingsRepository.settings
                .collectAsStateWithLifecycle(initialValue = AppSettings())

            ReelsDownloaderTheme(themeMode = settings.theme) {
                AppScaffold(
                    sharedUrl = sharedUrl,
                    onRequestNotificationPermission = ::requestNotificationPermission,
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        val action = intent?.action ?: return
        if (action != Intent.ACTION_SEND) return
        if (intent.type?.startsWith("text/") != true) return
        val text = intent.getStringExtra(Intent.EXTRA_TEXT) ?: return
        sharedUrl.value = text
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    companion object {
        const val EXTRA_JOB_ID = "extra_job_id"
    }
}

private enum class Tab(val icon: ImageVector, val labelRes: Int) {
    DOWNLOAD(AppIcons.Download, R.string.tab_download),
    HISTORY(AppIcons.History, R.string.tab_history),
    SETTINGS(AppIcons.Settings, R.string.tab_settings),
}

@Composable
private fun AppScaffold(
    sharedUrl: MutableStateFlow<String?>,
    onRequestNotificationPermission: () -> Unit,
) {
    var tab by remember { mutableStateOf(Tab.DOWNLOAD) }
    val homeViewModel: HomeViewModel = viewModel()
    val historyViewModel: HistoryViewModel = viewModel()
    val settingsViewModel: SettingsViewModel = viewModel()
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current

    val incoming by sharedUrl.collectAsStateWithLifecycle()

    val onHistoryEvent: (HistoryEvent) -> Unit = { event ->
        val message = when (event) {
            HistoryEvent.RemovedFromHistory -> context.getString(R.string.history_removed_from_history)
            HistoryEvent.DeletedWithFile -> context.getString(R.string.history_removed_with_file)
            HistoryEvent.FileDeleted -> context.getString(R.string.history_file_deleted)
            HistoryEvent.DeleteFailed -> context.getString(R.string.history_delete_failed_msg)
            is HistoryEvent.RemovedFailedEntries ->
                context.getString(R.string.history_removed_failed, event.count)

            is HistoryEvent.RemovedAll -> context.getString(R.string.history_removed_all, event.count)
            HistoryEvent.Retried -> context.getString(R.string.history_retried)
        }
        scope.launch {
            snackbarHostState.currentSnackbarData?.dismiss()
            snackbarHostState.showSnackbar(message)
        }
    }
    LaunchedEffect(incoming) {
        val url = incoming ?: return@LaunchedEffect
        homeViewModel.acceptSharedUrl(url)
        tab = Tab.DOWNLOAD
        sharedUrl.value = null
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            NavigationBar {
                Tab.entries.forEach { item ->
                    NavigationBarItem(
                        selected = tab == item,
                        onClick = { tab = item },
                        icon = { Icon(item.icon, contentDescription = null) },
                        label = { Text(stringResource(item.labelRes)) },
                    )
                }
            }
        },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        when (tab) {
            Tab.DOWNLOAD -> androidx.compose.foundation.layout.Box(modifier) {
                HomeScreen(
                    viewModel = homeViewModel,
                    onRequestNotificationPermission = onRequestNotificationPermission,
                )
            }

            Tab.HISTORY -> androidx.compose.foundation.layout.Box(modifier) {
                HistoryScreen(viewModel = historyViewModel, onEvent = onHistoryEvent)
            }

            Tab.SETTINGS -> androidx.compose.foundation.layout.Box(modifier) {
                SettingsScreen(viewModel = settingsViewModel)
            }
        }
    }
}

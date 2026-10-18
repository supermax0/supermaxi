package iq.finora.finora_phone.overlay

/**
 * One-shot launch payload from overlay / after-call notification → Flutter.
 * Carries action plus call context so cold-start after-call is usable.
 */
object PendingLaunchAction {
    @Volatile
    private var action: String? = null

    @Volatile
    private var number: String? = null

    @Volatile
    private var localCallUuid: String? = null

    fun set(
        action: String?,
        number: String? = null,
        localCallUuid: String? = null,
    ) {
        this.action = action
        if (number != null) this.number = number
        if (localCallUuid != null) this.localCallUuid = localCallUuid
    }

    fun clear() {
        action = null
        number = null
        localCallUuid = null
    }

    fun consume(): Map<String, String?> {
        val result = mapOf(
            "action" to action,
            "number" to number,
            "local_call_uuid" to localCallUuid,
        )
        clear()
        return result
    }

    fun peekAction(): String? = action
}

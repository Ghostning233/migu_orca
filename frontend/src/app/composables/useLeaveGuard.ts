/**
 * Route-local protection for work that cannot be safely abandoned.
 *
 * The guard is deliberately owned by the feature that owns the capability.
 * It only registers a browser unload listener while mounted and leaves an
 * inactive router guard behind after unmount; this avoids changing the shared
 * router's public contract while preventing stale component closures from
 * blocking later routes.
 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import { useRouter } from 'vue-router'

export interface LeaveGuardOptions {
  shouldGuard: () => boolean
  confirm: () => Promise<boolean>
  cleanup: () => void
}

export function useLeaveGuard(options: LeaveGuardOptions): { active: Ref<boolean> } {
  const router = useRouter()
  const active = ref(true)

  const onBeforeUnload = (event: BeforeUnloadEvent): void => {
    if (!active.value || !options.shouldGuard()) return
    event.preventDefault()
    // Required by browsers that still use returnValue to show the native
    // unload warning. The text is intentionally not user-controlled.
    event.returnValue = ''
  }

  router.beforeEach(async (to, from) => {
    if (!active.value || to.fullPath === from.fullPath || !options.shouldGuard()) return true
    const confirmed = await options.confirm()
    if (!confirmed) return false
    options.cleanup()
    return true
  })

  onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
  onBeforeUnmount(() => {
    active.value = false
    window.removeEventListener('beforeunload', onBeforeUnload)
  })

  return { active }
}

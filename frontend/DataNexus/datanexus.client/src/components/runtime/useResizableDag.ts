import { onBeforeUnmount, ref } from 'vue'

/** DAG 画布底边纵向拖拽；可向下扩展，也可拖回初始高度。 */
export function useResizableDag(initialHeight: number) {
  const canvasHeight = ref(initialHeight)
  const isResizing = ref(false)

  let startY = 0
  let startHeight = initialHeight
  let previousCursor = ''
  let previousUserSelect = ''

  function onPointerMove(event: PointerEvent) {
    if (!isResizing.value) return
    canvasHeight.value = Math.max(initialHeight, startHeight + event.clientY - startY)
  }

  function stopResize() {
    if (!isResizing.value) return
    isResizing.value = false
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', stopResize)
    window.removeEventListener('pointercancel', stopResize)
    document.body.style.cursor = previousCursor
    document.body.style.userSelect = previousUserSelect
  }

  function startResize(event: PointerEvent) {
    if (event.button !== 0) return
    event.preventDefault()
    startY = event.clientY
    startHeight = canvasHeight.value
    isResizing.value = true
    previousCursor = document.body.style.cursor
    previousUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'ns-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', stopResize)
    window.addEventListener('pointercancel', stopResize)
  }

  function resizeBy(delta: number) {
    canvasHeight.value = Math.max(initialHeight, canvasHeight.value + delta)
  }

  onBeforeUnmount(stopResize)

  return { canvasHeight, isResizing, startResize, resizeBy }
}

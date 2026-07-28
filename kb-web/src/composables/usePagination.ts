import { ref } from 'vue'

export function usePagination(defaultSize = 20) {
  const page = ref(1)
  const size = ref(defaultSize)
  const total = ref(0)

  function handlePageChange(newPage: number): void {
    page.value = newPage
  }

  function handleSizeChange(newSize: number): void {
    size.value = newSize
    page.value = 1
  }

  return {
    page,
    size,
    total,
    handlePageChange,
    handleSizeChange,
  }
}

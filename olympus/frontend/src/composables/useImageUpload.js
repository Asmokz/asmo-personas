/**
 * useImageUpload — File picker → base64 (resized to max 1024px).
 *
 * Usage:
 *   const { pickImage } = useImageUpload(onBase64)
 */
export function useImageUpload(onBase64) {
  function resizeAndEncode(file) {
    return new Promise((resolve) => {
      const reader = new FileReader()
      reader.onload = (e) => {
        const img = new Image()
        img.onload = () => {
          const MAX = 1024
          let { width, height } = img
          if (width > MAX || height > MAX) {
            if (width > height) { height = Math.round(height * MAX / width); width = MAX }
            else { width = Math.round(width * MAX / height); height = MAX }
          }
          const canvas = document.createElement('canvas')
          canvas.width = width
          canvas.height = height
          canvas.getContext('2d').drawImage(img, 0, 0, width, height)
          // Return pure base64 without data URL prefix
          const dataUrl = canvas.toDataURL('image/jpeg', 0.85)
          resolve(dataUrl.split(',')[1])
        }
        img.src = e.target.result
      }
      reader.readAsDataURL(file)
    })
  }

  function pickImage() {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.onchange = async () => {
      const file = input.files[0]
      if (!file) return
      const b64 = await resizeAndEncode(file)
      onBase64(b64)
    }
    input.click()
  }

  return { pickImage }
}

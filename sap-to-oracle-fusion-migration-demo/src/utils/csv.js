// CSV helpers built on papaparse for parsing uploads and generating downloads.
import Papa from 'papaparse'

// Serialize an array of row objects into a CSV string using the given header order.
export function rowsToCsv(headers, rows) {
  return Papa.unparse({ fields: headers, data: rows.map((r) => headers.map((h) => r[h] ?? '')) })
}

// Parse a File (from an <input type=file>) into an array of row objects.
export function parseCsvFile(file) {
  return new Promise((resolve, reject) => {
    Papa.parse(file, {
      header: true,
      skipEmptyLines: true,
      complete: (result) => resolve(result.data),
      error: (err) => reject(err),
    })
  })
}

// Trigger a browser download of the given text content as a file.
export function downloadText(filename, text, mime = 'text/csv;charset=utf-8;') {
  const blob = new Blob([text], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

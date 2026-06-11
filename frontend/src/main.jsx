import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthContext, useProvideAuth } from './lib/auth'
import './index.css'

function Root() {
  const auth = useProvideAuth()
  return (
    <AuthContext.Provider value={auth}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AuthContext.Provider>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
)

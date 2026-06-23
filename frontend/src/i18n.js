import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import en from './i18n/en.json'
import de from './i18n/de.json'

const stored = localStorage.getItem('tt_user')
const user = stored ? JSON.parse(stored) : null

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en }, de: { translation: de } },
    lng: user?.language || 'en',
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
  })

export default i18n

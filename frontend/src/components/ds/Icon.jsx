import {
  AlertCircle, ArrowDown, ArrowLeft, ArrowRight, ArrowLeftRight, ArrowUp, BarChart3, Building2, Calendar, CalendarClock, Check, CheckCircle2,
  ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clock, Download, ExternalLink, FileText, Filter, Folder, Globe,
  GripVertical, Home, Info, LayoutDashboard, LayoutGrid, Lock, LogOut, Mail, MapPin, Maximize2, Menu as MenuIcon, MessageSquare, MoreHorizontal,
  BadgePercent, Beer, BookUser, CarFront, Carrot, Pill, Package, PackageCheck, PackageX, PanelLeftClose, PanelLeftOpen, Pencil, Phone, Plus, Printer, RefreshCw,
  Database, Layers, Pin, PinOff, SlidersHorizontal, Table2, Wand2,
  Save, ScanBarcode, ShieldCheck, Search, Settings, Share2, ShoppingBag, ShoppingCart, Star, Store, Trash2, TrendingUp, TriangleAlert, Upload, UserRound, Users, Wallet, Wrench, X,
} from 'lucide-react'

const StarFilled = (props) => <Star fill="currentColor" {...props} />

// Lucide-style 2px stroke icons (DESIGN.md › Iconography). Names are the
// app's own; an unknown name renders nothing. (The old inline-SVG fallback
// set was dropped: it added ~45 KB to the first download and every one of
// its names is covered here.)
const LUCIDE = {
  dashboard: LayoutDashboard, 'dashboard-window': LayoutDashboard, pos: ShoppingCart, table: ShoppingCart,
  stock: Package, receiving: PackageCheck, transfer: ArrowLeftRight, share: Share2, customers: BookUser,
  analytics: BarChart3, 'visualization-bar': BarChart3, 'visualization-line': TrendingUp, reports: FileText,
  'file-document': FileText, settings: Settings, admin: Building2, folder: Folder, add: Plus, download: Download,
  upload: Upload, location: MapPin, cross: X, 'chevron-down': ChevronDown, 'chevron-up': ChevronUp,
  'chevron-left': ChevronLeft, 'chevron-right': ChevronRight, info: Info, 'info-filled': Info,
  'checkmark-circle': CheckCircle2, checkmark: Check, error: AlertCircle, 'error-filled': AlertCircle,
  warning: TriangleAlert, brand: ShoppingBag, store: Store, search: Search, 'log-out': LogOut, user: UserRound,
  'user-group': Users, 'panel-close': PanelLeftClose, 'panel-open': PanelLeftOpen, more: MoreHorizontal,
  clock: Clock, wallet: Wallet, 'package-x': PackageX, expiry: CalendarClock, calendar: Calendar, edit: Pencil,
  delete: Trash2, print: Printer, 'arrow-up': ArrowUp, 'arrow-down': ArrowDown, mail: Mail, sync: RefreshCw,
  filter: Filter, lock: Lock, star: Star, 'star-filled': StarFilled, save: Save, world: Globe, fullscreen: Maximize2, messages: MessageSquare,
  apps: LayoutGrid, 'drag-handle': GripVertical, launch: ExternalLink, menu: MenuIcon, promotion: BadgePercent, home: Home,
  barcode: ScanBarcode, database: Database, layers: Layers, pin: Pin, 'pin-off': PinOff, sliders: SlidersHorizontal,
  'pivot-table': Table2, wand: Wand2, 'arrow-right': ArrowRight, 'arrow-left': ArrowLeft, phone: Phone, grocery: Carrot, pharmacy: Pill, bar: Beer, shield: ShieldCheck, tools: Wrench, car: CarFront,
}

export default function Icon({ name, size = 18, style, className, strokeWidth = 2 }) {
  const Lucide = name && LUCIDE[name]
  if (!Lucide) return null
  return <Lucide size={size} strokeWidth={strokeWidth} className={className} style={{ flex: `0 0 ${size}px`, ...style }} aria-hidden="true" />
}

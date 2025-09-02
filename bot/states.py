from aiogram.fsm.state import StatesGroup, State

class RegStates(StatesGroup):
    waiting_phone = State()
    waiting_name  = State()

class PhotoStates(StatesGroup):
    waiting_photo = State()

class CaptainStates(StatesGroup):
    waiting_team_name = State()

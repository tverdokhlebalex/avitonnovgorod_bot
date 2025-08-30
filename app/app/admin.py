from fastapi import FastAPI
from sqladmin import Admin, ModelView
from app.database import engine
from app import models

class TeamAdmin(ModelView, model=models.Team):
    name_plural = "Teams"
    icon = "fa-solid fa-people-group"
    column_list = [models.Team.id, models.Team.name, models.Team.description, models.Team.created_at]
    form_columns = [models.Team.name, models.Team.description]
    column_searchable_list = [models.Team.name]

class UserAdmin(ModelView, model=models.User):
    name_plural = "Users"
    icon = "fa-regular fa-user"
    column_list = [
        models.User.id, models.User.tg_id, models.User.phone,
        models.User.last_name, models.User.first_name,
        models.User.is_active, models.User.created_at,
    ]
    form_columns = [
        models.User.tg_id, models.User.phone,
        models.User.last_name, models.User.first_name,
        models.User.is_active,
    ]
    column_searchable_list = [
        models.User.tg_id, models.User.phone,
        models.User.last_name, models.User.first_name,
    ]

class TeamMemberAdmin(ModelView, model=models.TeamMember):
    name_plural = "Team members"
    column_list = [
        models.TeamMember.id, models.TeamMember.team_id,
        models.TeamMember.user_id, models.TeamMember.role,
        models.TeamMember.created_at,
    ]
    form_columns = [models.TeamMember.team_id, models.TeamMember.user_id, models.TeamMember.role]

def mount_admin(app: FastAPI) -> Admin:
    admin = Admin(app, engine)
    admin.add_view(TeamAdmin)
    admin.add_view(UserAdmin)
    admin.add_view(TeamMemberAdmin)
    return admin
